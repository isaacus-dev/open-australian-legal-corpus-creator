import re
import asyncio

from datetime import datetime, timedelta
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor

import pytz
import aiohttp
import lxml.html
import aiohttp.client_exceptions

from striprtf.striprtf import rtf_to_text
from inscriptis.css_profiles import CSS_PROFILES
from inscriptis.html_properties import Display
from inscriptis.model.html_element import HtmlElement

from ..ocr import pdf2txt
from ..data import Entry, Request, Document, make_doc
from ..helpers import log, warning
from ..scraper import Scraper
from ..custom_mammoth import docx2html
from ..custom_inscriptis import CustomInscriptis, CustomParserConfig


class HighCourtOfAustralia(Scraper):
    """A scraper for the High Court of Australia database."""

    def __init__(self,
                 indices_refresh_interval: bool | timedelta = None,
                 index_refresh_interval: bool | timedelta = None,
                 semaphore: asyncio.Semaphore = None,
                 session: aiohttp.ClientSession = None,
                 thread_pool_executor: ThreadPoolExecutor = None,
                 ocr_semaphore: asyncio.Semaphore = None,
                 ) -> None:
        super().__init__(
            source='high_court_of_australia',
            indices_refresh_interval=indices_refresh_interval,
            index_refresh_interval=index_refresh_interval,
            semaphore=semaphore or asyncio.Semaphore(4), # NOTE We use a lower semaphore as the High Court of Australia database applies rate limiting.
            session=session,
            thread_pool_executor=thread_pool_executor,
            ocr_semaphore=ocr_semaphore,
        )

        self._type = 'decision'
        self._jurisdiction = 'commonwealth'

        # Steal the superclass's semaphore and then make it private.
        # NOTE Because it is possible for us to make multiple requests within a single function call, we need to use the semaphore on entire calls instead of individual requests, which is why we take it from the superclass.
        self._semaphore = self.semaphore
        self.semaphore = nullcontext()

        # NOTE We increase our wait times to account for the High Court of Australia database's rate limiting.
        self.stop_after_waiting += 30 * 60
        self.max_wait += 5 * 60
        self.wait_base += 2

        # Create a custom Inscriptis CSS profile.
        inscriptis_profile = CSS_PROFILES['strict'].copy()

        # Omit newlines after headings, but retain them before.
        inscriptis_profile |= dict.fromkeys(('h1', 'h2', 'h3', 'h4', 'h5'), HtmlElement(display=Display.block, margin_before=1))

        # Create an Inscriptis parser config using the custom CSS profile.
        self._inscriptis_config = CustomParserConfig(inscriptis_profile)

        # Create map of button names to their document types.
        self._button_types = {
            'PDF': 'PDF',
            'DOCX' : 'DOCX',
            'RTF' : 'RTF',
            'View': 'PDF',
            'Download': 'PDF',
        }

    @log
    async def get_index_reqs(self) -> set[Request]:
        # Get the current year in Canberra.
        year = datetime.now(tz=pytz.timezone("Australia/Canberra")).strftime(r"%Y")

        # Generate requests for every base search engine results page ('SERP').
        # NOTE `col=0` is for the 'Judgments (2000-current)' collection, `col=1` for 'Judgments (1948-1999)', `col=2` for 'One-100 Project' and `historical/search?col=0` is for the 'Unreported Judgments' collection.
        base_serps = {f'https://eresources.hcourt.gov.au/search?col={dataset_id}&filter_4=0+TO+{year}' for dataset_id in range(0, 3)} | {f'https://eresources.hcourt.gov.au/historical/search?col=0&filter_4=0+TO+{year}'}

        # Generate requests for every page of every base SERP.
        index_reqs = await asyncio.gather(*[self._get_index_reqs_from_base_serp(base_serp) for base_serp in base_serps])

        # Flatten and return the requests.
        return set().union(*index_reqs)

    @log
    async def _get_index_reqs_from_base_serp(self, base_serp: str) -> set[Request]:
        """Retrieve a set of requests for every page of a base search engine results page ('SERP')."""

        # Retrieve the base SERP.
        resp = (await self.get(base_serp)).text

        # Determine the number of pages in the base SERP.
        pages = int(re.search(r'<span\s+id="lastItem"\s*>(\d+)</span\s*>', resp).group(1).replace(',', '').replace(' ', ''))

        # Generate requests for every page of the base SERP.
        return {Request(f'{base_serp}&page={page}') for page in range(1, pages + 1)}

    @log
    async def get_index(self, req: Request) -> set[Entry]:
        # Retrieve the index.
        resp = (await self.get(req)).text

        # Extract entries from the index.
        return {
            Entry(
                request=Request(f'https://eresources.hcourt.gov.au{slug}'),
                version_id=slug,
                source=self.source,
                type=self._type,
                jurisdiction=self._jurisdiction,
                title=''.join(re.search(r'<strong\s*>((?:.|\n)*?)</strong\s*>(?:(?:.|\n)*?)<span\s+style="\s*white-space:\s*nowrap;\s*"\s*>((?:.|\n)*?)</span\s*>', title_html).groups()),
            )

            for slug, title_html in re.findall(r'<a\s+class="case"\s+href="([^"]+)"\s*>((?:.|\n)*?)</a\s*>', resp)
        }

    @log
    async def _get_doc(self, entry: Entry) -> Document | None:
        async with self._semaphore:
            # Retrieve the document.
            resp = await self.get(entry.request)

            # Store the url of the document so that we may overwrite it if necessary.
            url = entry.request.path

            # Extract the date of the document if available.
            if date := re.search(r'<h2>(\d{1,2} [A-Z][a-z]+ \d{4})</h2>', resp.text):
                date = datetime.strptime(date.group(1), '%d %b %Y').strftime('%Y-%m-%d')

            # NOTE Documents in the High Court of Australia database will either be HTML only or will be stored as PDFs, DOCXs, DOCs and/or RTFs. If a download button exists, that means that the document is not available as HTML. Therefore, we begin searching for whether that is the case.
            if download_links:=re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(PDF|View|Download|DOCX|RTF)</a>', resp.text):
                # NOTE We use the last link because the first link is always PDF and we prefer other document types over PDFs.
                slug, type_ = download_links[-1]

                url = f'https://eresources.hcourt.gov.au{slug}'

                # Determine the document's type.
                type_ = self._button_types[type_]

                # Retrieve the document.
                resp = await self.get(url)

                # Return `None` if the document is missing.
                if b'Document could not be found' in resp or b'There were no matching cases.' in resp:
                    warning(f"Unable to extract text from '{entry.request.path}' as it appears to be missing. Returning `None`.")
                    
                    return

            else:
                type_ = 'HTML'

            match type_:
                case 'RTF':
                    # If a `UnicodeDecodeError` is raised, then we know that the document is actually a DOC (despite the fact that it was labelled an RTF).
                    try:
                        text = rtf_to_text(resp.text, encoding='cp1252', errors='ignore')

                        # Store the mime of the document.
                        mime = 'application/rtf'

                    except UnicodeDecodeError:
                        # Convert the document to HTML.
                        # NOTE Converting DOCX files to HTML with `mammoth` outperforms using `pypandoc`, `python-docx`, `docx2txt` and `docx2python` to convert DOCX files directly to text.
                        html = docx2html(resp.stream)

                        # Extract text from the generated HTML.
                        etree = lxml.html.fromstring(html.value)
                        text = CustomInscriptis(etree, self._inscriptis_config).get_text()

                        # Store the mime of the document.
                        mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

                case 'DOCX':
                    # Convert the document to HTML.
                    # NOTE Converting DOCX files to HTML with `mammoth` outperforms using `pypandoc`, `python-docx`, `docx2txt` and `docx2python` to convert DOCX files directly to text.
                    html = docx2html(resp.stream)

                    # Extract text from the generated HTML.
                    etree = lxml.html.fromstring(html.value)
                    text = CustomInscriptis(etree, self._inscriptis_config).get_text()

                    # Store the mime of the document.
                    mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

                case 'PDF':
                    # Extract the text of the document from the PDF with OCR.
                    # NOTE We use a scale of 2 instead of the default of 3 because the PDFs on the High Court of Australia database are *extremely* slow to OCR.
                    text = await pdf2txt(resp.stream, self.ocr_batch_size, self.thread_pool_executor, self.ocr_semaphore, scale=2)

                    # Store the mime of the document.
                    mime = 'application/pdf'

                case 'HTML':
                    # Construct an etree from the response.
                    etree = lxml.html.fromstring(resp.text)

                    # Retrieve the element containing the text of the decision.
                    text_elm = etree.xpath('//div[@class="wellCase"]')[0]

                    # Extract the text of the decision.
                    text = CustomInscriptis(text_elm, self._inscriptis_config).get_text()

                    # Remove newlines from the beginning of the text.
                    text = re.sub(r'^\n+', '', text)

                    # Store the mime of the document.
                    mime = 'text/html'

            # Create the document.
            return make_doc(
                version_id=entry.version_id,
                type=entry.type,
                jurisdiction=entry.jurisdiction,
                source=entry.source,
                mime=mime,
                date=date,
                citation=entry.title,
                url=url,
                text=text,
            )