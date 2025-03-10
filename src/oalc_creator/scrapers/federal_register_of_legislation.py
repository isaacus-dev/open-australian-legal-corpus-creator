import re
import random
import asyncio

from math import ceil
from zipfile import BadZipFile
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import lxml.html
import lxml.etree

from pypdfium2 import PdfiumError
from inscriptis.css_profiles import CSS_PROFILES
from inscriptis.html_properties import Display, WhiteSpace
from inscriptis.model.html_element import HtmlElement

from ..ocr import pdf2txt
from ..data import Entry, Request, Document, make_doc, Response
from ..helpers import log, warning
from ..scraper import Scraper, ParseError
from ..custom_mammoth import docx2html
from ..custom_inscriptis import CustomInscriptis, CustomParserConfig
from contextlib import nullcontext


class FederalRegisterOfLegislation(Scraper):
    """A scraper for the Federal Register of Legislation database."""
    
    def __init__(self,
                 indices_refresh_interval: bool | timedelta = None,
                 index_refresh_interval: bool | timedelta = None,
                 semaphore: asyncio.Semaphore = None,
                 session: aiohttp.ClientSession = None,
                 thread_pool_executor: ThreadPoolExecutor = None,
                 ocr_semaphore: asyncio.Semaphore = None,
                 ) -> None:
        super().__init__(
            source='federal_register_of_legislation',
            indices_refresh_interval=indices_refresh_interval,
            index_refresh_interval=index_refresh_interval,
            semaphore=semaphore,
            session=session,
            thread_pool_executor=thread_pool_executor,
            ocr_semaphore=ocr_semaphore,
        )
        
        # Steal the superclass's semaphore and then make it private.
        # NOTE Because it is possible for us to make multiple requests within a single function call, we need to use the semaphore on entire calls instead of individual requests, which is why we take it from the superclass.
        self._semaphore = self.semaphore
        self.semaphore = nullcontext()
        
        # Add status codes to the list of status codes to retry on that are transient errors that occur when the Federal Register of Legislation's servers are overloaded.
        self.retry_statuses += (502, 400,)

        # Create a custom Inscriptis CSS profile.
        inscriptis_profile = CSS_PROFILES['strict'].copy()
        
        # Omit additional newlines before and after `p` elements.
        inscriptis_profile['p'] = HtmlElement(display=Display.block)
        
        # Preserve the indentation of `span` elements with whitespace.
        inscriptis_profile['span'] = HtmlElement(whitespace=WhiteSpace.pre)
        
        # Omit newlines after headings, but retain them before.
        inscriptis_profile |= dict.fromkeys(('h1', 'h2', 'h3', 'h4', 'h5'), HtmlElement(display=Display.block, margin_before=1))
        
        # Create an Inscriptis parser config using the custom CSS profile.
        self._inscriptis_config = CustomParserConfig(inscriptis_profile)
        
        # Define the maximum number of documents that can be returned by a search engine results page ('SERP').
        self._docs_per_serp = 100
        
        # Map database collection names to document types and jurisdictions.
        self._collections = {
            'Constitution': ('primary_legislation', 'commonwealth'),
            'Act': ('primary_legislation', 'commonwealth'),
            'LegislativeInstrument': ('secondary_legislation', 'commonwealth'),
            'NotifiableInstrument': ('secondary_legislation', 'commonwealth'),
            'AdministrativeArrangementsOrder': ('secondary_legislation', 'commonwealth'),
            'PrerogativeInstrument': ('secondary_legislation', 'commonwealth'),
            'ContinuedLaw': (None, 'norfolk_island'),
        }

    @log
    async def get_index_reqs(self) -> set[Request]:
        # Retrieve the first search engine results page ('SERP') to determine the total number of pages.
        async with self._semaphore:
            first_page = await self.get(
                f"""https://api.prod.legislation.gov.au/v1/titles/search(
                    criteria = 'and(
                            collection(
                                {','.join(self._collections)}
                                ),
                            status(InForce)
                        )'
                )?
                $top=0""".replace('\n', '').replace(' ', '') # Remove newlines and spaces that were inserted into the url template for readability.
            )
        
            total_docs = first_page.json['@odata.count']
            total_pages = ceil(total_docs/self._docs_per_serp)
            
            # Generate requests for every page of results.
            # NOTE It is extremely important that we include `orderby = searchcontexts/fulltextversion/registeredat%20asc`. Not doing so leads the results to be sorted by relevance and, for whatever reason, relevance seems to be non-deterministic in that, if you go through all the pages, you will find duplicate results, leading to other results being missed. It is possible this occurs because new documents have been added but that is unlikely seeing as this has occured multiple times on different occasions.
            return {
                Request(
                    f"""https://api.prod.legislation.gov.au/v1/titles/search(
                        criteria = 'and(
                                collection(
                                    Constitution,
                                    Act,
                                    LegislativeInstrument,
                                    NotifiableInstrument,
                                    AdministrativeArrangementsOrder,
                                    PrerogativeInstrument,
                                    ContinuedLaw),
                                status(InForce)
                            )'
                    )?
                    &$ select = collection, id, name, searchContexts
                    &$ expand = searchContexts($expand=fullTextVersion)
                    &$ orderby = searchcontexts/fulltextversion/registeredat%20asc
                    &$ top = {self._docs_per_serp}
                    &$ skip = {self._docs_per_serp*page}""".replace('\n', '').replace(' ', '') # Remove newlines and spaces that were inserted into the url template for readability.
                )
                
                for page in range(total_pages)
            }
    
    @log
    async def get_index(self, req: Request) -> set[Entry]:
        # Retrieve the index.
        async with self._semaphore:
            resp = (await self.get(req))
        
            # Raise an exception if no results were returned.
            if len(resp.json['value']) == 0:
                raise Exception(f'No entries were found for the request:\n{req}')
            
            # Extract entries from the index.
            return {
                Entry(
                    request = Request(f"https://www.legislation.gov.au/{entry['id']}"),
                    version_id=entry['searchContexts']['fullTextVersion']['registerId'],
                    source=self.source,
                    type=self._collections[entry['collection']][0], # NOTE it is possible for the document type to be `None` (eg, for Norfolk Island legislation); in such cases, the document type is determined when retrieving the document.
                    jurisdiction=self._collections[entry['collection']][1],
                    date=entry['searchContexts']['fullTextVersion']['start'][:10], # Extract the date part of the date-time string.
                    title=entry['name'],
                )
                
                for entry in resp.json['value']
            }

    @log
    async def get(self, req: Request | str) -> Response:
        attempt = 0
        elapsed = 0
        
        while True:
            try:
                content = await super().get(req)
                
                if b'The service is unavailable.' in content:
                    raise ParseError("The Federal Register of Legislation's servers are currently overloaded.")
                
                return content
            
            except ParseError as e:
                if elapsed > self.stop_after_waiting:
                    raise e
                
                attempt += 1
                
                # Implement exponential backoff with jitter.
                wait = self.wait_base ** attempt / 2 # We divide by 2 so that `wait + jitter` is always <= `self.wait_base ** attempt`.
                
                # Set our jitter to a random number between 0 and `wait`.
                jitter = random.uniform(0, wait)
                
                wait += jitter
                
                # If `wait` is greater than `self.max_wait`, set `wait` to `self.max_wait`.
                wait = min(wait, self.max_wait)

                # Add a little extra jitter to the wait time to handle cases where `wait` has been capped at `self.max_wait`.
                wait += random.uniform(0, self.max_extra_jitter)
                
                # Wait for `wait` seconds.
                await asyncio.sleep(wait)
                
                elapsed += wait

    @log
    async def _get_doc(self, entry: Entry) -> Document | None:
        async with self._semaphore:
            # If no document type was set, determine the document type from the title.
            if entry.type is None:
                # NOTE This regex only matches primary legislation for Norfolk Island as Norfolk Island is currently the only jurisdiction for which the document type will not already be set.
                if re.search(r'^.*\sAct\s+\d{4}\s+\(NI\)\s*$', entry.title):
                    type = 'primary_legislation'
                
                else:
                    type = 'secondary_legislation'
            
            else:
                type = entry.type
            
            # Retrieve the document's status page.
            status_page = await self.get(entry.request)
            
            # Extract the links to the HTML full text of the document's constituent parts if they exist otherwise search for other versions of the document.        
            urls = re.findall(r'href="([^"]+)" target="epubFrame"', status_page.text)
            urls = [url.split('#')[0] for url in urls] # Remove any anchors from the urls, which will assist with deduplication.
            
            if not urls: # If no links to the HTML full text of the document's constituent parts could be found (in the navigation pane), search for a link to the HTML full text of the first part of the document (in the text viewer's iframe) if that exists.
                urls = re.findall(r'<iframe[^>]+name="epubFrame"[^>]+src="([^"]+)">', status_page.text)
            
            urls = list(dict.fromkeys(urls)) # Remove duplicate urls.
            
            if urls:
                # If there is a single part, use its link as the url otherwise use the document's status page as its url.
                url = urls[0] if len(urls) == 1 else entry.request.path

                # Retrieve the full text of the document's constituent parts.
                resps = await asyncio.gather(*[self.get(url) for url in urls])
                
                # Create etrees from the responses.
                etrees = [lxml.html.document_fromstring(resp) for resp in resps]
                    
                # Extract the text of the document's constituent parts.
                texts = [CustomInscriptis(etree, self._inscriptis_config).get_text() for etree in etrees]

                # Store the mime of the document.
                mime = 'text/html'
            
            # If there is no link to the document's HTML full text, search for other versions of the document.
            else:
                url = f'{entry.request.path}/latest/downloads'
                downloads_page = await self.get(url)
                downloads_page_etree = lxml.html.document_fromstring(downloads_page)
                
                # If there are no available versions of the document, log a warning and return `None`.
                downloads = downloads_page_etree.xpath("//*[contains(concat(' ', normalize-space(@class), ' '), ' download-list-primary ')]")
                
                if not downloads:
                    warning(f'Unable to retrieve document from {entry.request.path}. No valid version found. The status code of the response was {downloads_page.status}. Returning `None`.')
                    return
                
                # Search for Word and then PDF versions of the document.
                for format in ('word', 'pdf'):
                    format_downloads = downloads[0].xpath(f".//*[contains(concat(' ', normalize-space(@class), ' '), ' document-format-{format} ')]")
                    
                    # Skip to the next format if the document is not available in this format.
                    if not format_downloads:
                        continue
                    
                    # Extract links to the version's constituent parts.
                    part_links = format_downloads[0].xpath(".//a/@href")
                    
                    # Skip to the next format if there are no links to the document in this format.
                    if not part_links:
                        continue
                    
                    break
                
                # If there are neither any Word nor any PDF versions of the document, log a warning and return `None`.
                else:
                    warning(f'Unable to retrieve document from {entry.request.path}. No valid version found. This may be because the document simply does not have any versions available, or it could be that any versions it does have available are unsupported. The status code of the response was {downloads_page.status}. Returning `None`.')
                    return
                
                # If there is just one part, use its link as the url.
                if len(part_links) == 1:
                    url = str(part_links[0]) # NOTE It is necessary to convert the link from a `lxml.etree._ElementUnicodeResult` instance into a string so that it can deserialised by `msgspec` (bizarrely, its type checker does not pick up on such instances not technically being strings, which makes sense since they behave like strings, but then when you attempt to actually encode it, you will run into errors).
                
                # Retrieve the version's constituent parts.
                part_resps = await asyncio.gather(*[self.get(part_link) for part_link in part_links])
                
                # Extract the text of the version's parts.
                if format == 'word':
                    # Convert the parts to HTML.
                    # NOTE Converting DOCX files to HTML with `mammoth` outperforms using `pypandoc`, `python-docx`, `docx2txt` and `docx2python` to convert DOCX files directly to text.
                    # NOTE Some documents in the database are stored as DOC files and there is absolutely no indication beforehand whether a document will be a DOC or DOCX, thus, we need to check if a `BadZipFile` or `ParserError` exception is raised and if it is, check if there are any PDF versions we can scrape instead. It is also technically possible to convert DOC files to DOCX but there are only two Python libraries capable of doing so and one of them (`doc2docx`) is dependant on Microsoft Word being installed and so only supports Windows and Mac and also does not work on Python 3.12 (https://github.com/cosmojg/doc2docx/issues/2) and the other library (`Spire.Doc`) is paid.
                    try:
                        htmls = [docx2html(resp.stream) for resp in part_resps]
                    
                        # Extract text from the generated HTML.
                        etrees = [lxml.html.fromstring(html.value) for html in htmls]
                        texts = [CustomInscriptis(etree, self._inscriptis_config).get_text() for etree in etrees]
                        
                        # Store the mime of the document.
                        mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    
                    except (BadZipFile, lxml.etree.ParserError):
                        # Log a warning.
                        warning(f"Unable to convert '{entry.request.path}' to HTML as it is stored as a .DOC file and not a .DOCX file and the parsing of .DOC files is not supported. Looking for a PDF version to scrape instead and, if one is not found, returning `None`.")
                        
                        # Search for PDF versions of the document.
                        format = 'pdf'
                        format_downloads = downloads[0].xpath(f".//*[contains(concat(' ', normalize-space(@class), ' '), ' document-format-{format} ')]")
                        
                        if not format_downloads or not (part_links := format_downloads[0].xpath(".//a/@href")):
                            # NOTE As of 1 June 2024, there are no documents that are stored as DOC files but do not also have a PDF version. Nevertheless, we log a warning just in case that ever changed somehow.
                            warning(f'Unable to retrieve document from {entry.request.path}. No valid version found. This may be because the document simply does not have any versions available, or it could be that any versions it does have available are unsupported. The status code of the response was {downloads_page.status}. Returning `None`.')
                            return
                        
                        # If there is just one part, use its link as the url.
                        if len(part_links) == 1:
                            url = str(part_links[0])
                        
                        # Retrieve the version's constituent parts.
                        part_resps = await asyncio.gather(*[self.get(part_link) for part_link in part_links])
                                
                if format == 'pdf':
                    # Extract the text of the document from its PDF parts.
                    try:
                        texts = await asyncio.gather(*[pdf2txt(resp.stream, self.ocr_batch_size, self.thread_pool_executor, self.ocr_semaphore) for resp in part_resps])
                    
                    except PdfiumError as e:
                        # Log a warning.
                        warning(f"Unable to extract text from '{entry.request.path}' as it or one of its constituent parts does not appear to be a valid PDF. The error message was: {e} It is possible that this is a transient error caused by the server being overloaded. Returning `None`.")
                        
                        return

                    # Store the mime of the document.
                    mime = 'application/pdf'

            # Stitch together the version's parts to form the full text of the version.
            text = '\n'.join(texts)
                
            # Return the document.
            return make_doc(
                version_id=entry.version_id,
                type=type,
                jurisdiction=entry.jurisdiction,
                source=entry.source,
                mime=mime,
                date=entry.date,
                citation=entry.title,
                url=url,
                text=text
            )