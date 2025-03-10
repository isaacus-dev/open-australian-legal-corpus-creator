import os
import random
import shutil
import asyncio
import os.path
import pathlib
import multiprocessing

from typing import Iterable
from datetime import datetime
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor

import aiohttp

from msgspec import DecodeError
from platformdirs import user_data_dir
from tqdm.asyncio import tqdm_asyncio
from rich.markdown import Markdown

from .data import encoder, Entries, Request, entries_decoder, document_decoder, requests_decoder
from .helpers import log, console, warning, load_json, save_json, load_jsonl, save_jsonl
from .scraper import Scraper
from .metadata import DATA_VERSIONS
from .scrapers import (NswCaselaw, NswLegislation, HighCourtOfAustralia, TasmanianLegislation, QueenslandLegislation,
                       FederalCourtOfAustralia, SouthAustralianLegislation, FederalRegisterOfLegislation,
                       WesternAustralianLegislation)

# Initialise a map of the names of sources to their scrapers.
SOURCES: dict[str, Scraper] = {
    'federal_court_of_australia' : FederalCourtOfAustralia,
    'federal_register_of_legislation' : FederalRegisterOfLegislation,
    'high_court_of_australia' : HighCourtOfAustralia,
    'nsw_caselaw' : NswCaselaw,
    'nsw_legislation' : NswLegislation,
    'queensland_legislation' : QueenslandLegislation,
    'south_australian_legislation' : SouthAustralianLegislation,
    'western_australian_legislation' : WesternAustralianLegislation,
    'tasmanian_legislation' : TasmanianLegislation,
}

class Creator:
    """The creator of the Open Australian Legal Corpus."""
    
    def __init__(self,
                 sources: Iterable[str | Scraper] = None,
                 corpus_path: str = None,
                 data_dir: str = None,
                 num_threads: int = None,
                 max_concurrent_ocr: int = None,
                 ) -> None:
        """Initialise the creator of the Open Australian Legal Corpus.
        
        Args:
            sources (Iterable[str | Scraper], optional): The names of the sources to be scraped or the scrapers themselves. Possible sources are `federal_court_of_australia`, `federal_register_of_legislation`, `high_court_of_australia`, `nsw_caselaw`, `nsw_legislation`, `queensland_legislation`, `south_australian_legislation`, `western_australian_legislation` and `tasmanian_legislation`. Defaults to all supported sources.
            corpus_path (str, optional): The path to the Corpus. Defaults to a file named `corpus.jsonl` in the current working directory.
            data_dir (str, optional): The path to the directory in which Corpus data should be stored. Defaults to the user's data directory as determined by `platformdirs.user_data_dir` (on Windows, this will be `C:/Users/<username>/AppData/Local/Umar Butler/Open Australian Legal Corpus`).
            num_threads (int, optional): The number of threads to use for OCRing PDFs with `tesseract`. Defaults to the number of logical CPUs on the system minus one, or one if there is only one logical CPU.
            max_concurrent_ocr (int, optional): The maximum number of PDFs that may be OCR'd concurrently. Defaults to 1."""
        
        # Initialise a thread pool executor.
        num_threads = num_threads or multiprocessing.cpu_count() - 1 or 1
        thread_pool_executor = ThreadPoolExecutor(num_threads)
        
        # Initialise a semaphore for limiting the number of PDFs that may be OCR'd concurrently.
        ocr_semaphore = asyncio.Semaphore(max_concurrent_ocr or 1)

        # Initialise the scrapers.
        sources = sources or SOURCES.keys()
        self.scrapers = {(SOURCES[source]() if not isinstance(source, Scraper) else source) for source in sources}
        
        for scraper in self.scrapers:
            scraper.thread_pool_executor = thread_pool_executor
            scraper.ocr_semaphore = ocr_semaphore
        
        self.scrapers: dict[str, Scraper] = {scraper.source : scraper for scraper in self.scrapers}
        """A map of the names of sources to their scrapers."""

        # Initialise paths.
        cwd = os.getcwd()
        
        self.corpus_path = corpus_path or 'corpus.jsonl'
        self.corpus_path: str = os.path.join(cwd, self.corpus_path) # NOTE We join the current working directory to the Corpus path to ensure the path is relative to the current working directory, not the location of this module.
        """The path to the Corpus."""
        
        self.data_dir = data_dir or user_data_dir('Open Australian Legal Corpus', 'Umar Butler')
        self.data_dir: str = os.path.join(cwd, self.data_dir)
        """The path to the directory in which Corpus data is stored."""
        
        self.indices_dir: str = os.path.join(self.data_dir, 'indices')
        """The path to the directory in which requests for document indices are stored."""
        
        self.index_dir: str = os.path.join(self.data_dir, 'index')
        """The path to the directory in which document indices are stored."""
        
        versions_path: str = os.path.join(self.data_dir, 'versions.json')
        
        # Check for a `versions.json` file in the data directory.
        if os.path.exists(versions_path):
            # Load the versions file.
            versions = load_json(versions_path)
            
            # Create a map of the names of data to their paths.
            data_paths = {
                'corpus' : self.corpus_path,
                'indices' : self.indices_dir,
                'index' : self.index_dir,
            }
            
            # Delete any data that is incompatible with the current version of the Creator.
            for name, version in versions.items():
                # If the data in `data_paths` is incompatible with the current version of the Creator, delete it.
                if name in data_paths and version != DATA_VERSIONS[name] and os.path.exists(data_paths[name]):
                    if os.path.isdir(data_paths[name]):
                        shutil.rmtree(data_paths[name])
                    
                    else:
                        pathlib.Path.unlink(data_paths[name])
        
        # Create any necessary directories.
        for path in [self.indices_dir, self.index_dir, os.path.dirname(self.corpus_path)]:
            if path: os.makedirs(path, exist_ok=True)
        
        # Create the Corpus file if it does not exist.
        if not os.path.exists(self.corpus_path):
            with open(self.corpus_path, 'w') as _: pass

        # Create the versions file.
        save_json(versions_path, DATA_VERSIONS)
    
    @log
    async def _get_index_reqs(self, scraper: Scraper) -> set[Request]:
        """Load or retrieve and save a set of requests for document indices from a scraper."""
        
        path = os.path.join(self.indices_dir, f'{scraper.source}.json')
        
        # If the requests have not yet been saved, the source's indices refresh interval is set to True, or the interval is not False and the saved requests are older than the interval, generate and save new requests.
        if not os.path.exists(path) or scraper.indices_refresh_interval is True or (
            scraper.indices_refresh_interval is not False and
            datetime.now() - datetime.fromtimestamp(os.path.getmtime(path)) > scraper.indices_refresh_interval
        ):
            save_json(path, reqs := await scraper.get_index_reqs())
        
        # Otherwise, load the saved requests.
        else:
            reqs = load_json(path, decoder = requests_decoder)
        
        return reqs
    
    @log
    def _get_unindexed_index_reqs(self, scraper: Scraper, index_reqs: set[Request]) -> set[Request]:
        """Identify requests for document indices of the given source that have not yet been indexed, and remove from the source's index any requests that do not appear in the provided requests or are older than the source's index refresh interval."""
        
        path = os.path.join(self.index_dir, f'{scraper.source}.jsonl')
        
        # If the index does not yet exist, return the provided set of requests.
        if not os.path.exists(path):
            return index_reqs
        
        # If the source's index refresh interval is set to True, delete the index and then return the provided set of requests.
        if scraper.index_refresh_interval is True:
            pathlib.Path.unlink(path)
            
            return index_reqs
        
        # Load requests from the index.
        index: list[Entries] = load_jsonl(path, decoder = entries_decoder)
        
        # Preserve the length of the index before filtering to determine whether to overwrite the index.
        index_len = len(index)
        
        # Filter for requests that appear in the provided set of requests and, if the source's index refresh interval is not False, are also not older than the source's index refresh interval.
        index = [entries for entries in index if entries.request in index_reqs and (
            scraper.index_refresh_interval is False or
            datetime.now() - datetime.fromtimestamp(entries.when_indexed) <= scraper.index_refresh_interval
        )]
        
        # If the length of the index has changed (ie, there are requests in the saved index that do not appear in the provided set of requests or, if the source's index refresh interval is not False, are older than the source's index refresh interval), overwrite the index.
        if len(index) != index_len:
            save_jsonl(path, index)
        
        # Return any requests that are missing from the index.
        return index_reqs - {entries.request for entries in index}

    @log
    async def _get_index(self, scraper: Scraper, req: Request) -> tuple[str, Entries]:
        """Retrieve entries from a document index and return the name of the source along with the entries."""
        
        return scraper.source, Entries(
            request = req,
            entries = await scraper.get_index(req),
            when_indexed = datetime.now().timestamp(),
        )
        
    async def create(self) -> None:
        """Update the Corpus."""
        
        console.print(Markdown('# Open Australian Legal Corpus Creator'), style='light_cyan1')

        # Create a new `aiohttp` session using a with statement to ensure that the session is always closed.
        async with aiohttp.ClientSession() as session:
            # Set the scrapers' sessions to the new session. This improves performance vis-a-vis creating new sessions for each request.
            for scraper in self.scrapers.values(): scraper.session = session

            # Get requests for document indices.
            console.print('Determining what document indices must be searched in order to create an index of documents to be included in the Corpus.', style='light_cyan1 bold')
            index_reqs = await tqdm_asyncio.gather(*[self._get_index_reqs(scraper) for scraper in self.scrapers.values()])
            
            # Determine which document indices have not yet been indexed and attach their scrapers.
            unindexed_index_reqs = [[scraper, self._get_unindexed_index_reqs(scraper, reqs)] for scraper, reqs in zip(self.scrapers.values(), index_reqs)]
            
            # Flatten the requests but retain their scrapers.
            unindexed_index_reqs = [[scraper, req] for scraper, reqs in unindexed_index_reqs for req in reqs]
            
            # Randomly shuffle the requests.
            random.shuffle(unindexed_index_reqs)
        
            # Index unindexed document indices if there are any.
            if unindexed_index_reqs:
                console.print('\nSearching for documents to be included in the Corpus.', style='light_cyan1 bold')
                
                # Identify sources with unindexed document indices.
                sources_with_unindexed_indices = {scraper.source for scraper, _ in unindexed_index_reqs}
                
                # Open the sources' index files.
                # NOTE We use an ExitStack to ensure that the files are always closed even if an exception is raised.
                with ExitStack() as stack:
                    index_files = {source : stack.enter_context(open(os.path.join(self.index_dir, f'{source}.jsonl'), 'ab')) for source in sources_with_unindexed_indices}
                    
                    # Append requests, entries and the time they were indexed to the sources' index files as they are indexed.
                    for source_index in tqdm_asyncio.as_completed([self._get_index(scraper, req) for scraper, req in unindexed_index_reqs]):
                        source, index = await source_index
                        
                        index_files[source].write(encoder(index))
                        index_files[source].write(b'\n')
            
            # Load sources' indices and attach their scrapers.
            indices: list[tuple[Scraper, list[Entries]]] = [[scraper, load_jsonl(os.path.join(self.index_dir, f'{scraper.source}.jsonl'), decoder = entries_decoder)] for scraper in self.scrapers.values()]
            
            # Flatten document entries but retain their scrapers.
            # NOTE We use a dictionary comprehension to deduplicate document entries by version id (this is important as there is at least one bug known to cause duplicate entries (the problem is with the Federal Court of Australia's database)).
            entries = {
                entry.version_id : [scraper, entry]
                
                for scraper, index in indices
                for entries in index
                for entry in entries.entries
            }
            
            # Index the version ids of documents in the Corpus from the desired sources in order to later identify missing documents to be added to the Corpus and also determine whether it is necessary to deduplicate, repair and/or remove outdated documents (in particular, documents that have the same source as the sources being scraped and do not appear in the sources' indices) from the Corpus.
            corpus_version_ids = set()
            corpus_line_numbers_to_remove = set()
            
            with open(self.corpus_path, 'rb') as corpus_file:
                for i, line in enumerate(corpus_file):
                    try:
                        doc = document_decoder(line)
                    
                    except DecodeError as e:
                        warning(f"Failed to decode document #{i + 1:,} when loading the Corpus. The error encountered was: '{e}'. The document will be treated as corrupted and will be removed from the Corpus.")
                        corpus_line_numbers_to_remove.add(i)
                        continue
                    
                    version_id = doc.version_id
                    source = doc.source
                    
                    if version_id in corpus_version_ids or (version_id not in entries and source in self.scrapers):
                        corpus_line_numbers_to_remove.add(i)
                    
                    elif source in self.scrapers:
                        corpus_version_ids.add(version_id)
            
            # Deduplicate, repair and/or remove outdated documents (in particular, documents that have the same source as the sources being scraped and do not appear in the sources' indices) from the Corpus.
            if corpus_line_numbers_to_remove:
                console.print('\nDeduplicating, repairing and/or removing outdated documents from the Corpus.', style='light_cyan1 bold')
                
                with open(self.corpus_path, 'rb') as corpus_file, open(f'{self.corpus_path}.tmp', 'wb') as tmp_file:
                    for i, line in enumerate(corpus_file):
                        if i not in corpus_line_numbers_to_remove:
                            tmp_file.write(line)
            
                # Overwrite the Corpus with the temporary file.
                os.replace(f'{self.corpus_path}.tmp', self.corpus_path)
                
            # Identify missing documents by filtering out from the document entries any documents that already appear in the Corpus.
            missing_entries = [scraper_entry for version_id, scraper_entry in entries.items() if version_id not in corpus_version_ids]
            
            # If there are no missing documents, return.
            if not missing_entries:
                console.print('\nThe Corpus is already up to date.', style='dark_cyan bold')
                return
            
            # Randomly shuffle the missing documents.
            random.shuffle(missing_entries)
            
            # Add missing documents to the Corpus.
            console.print('\nAdding documents to the Corpus.', style='light_cyan1 bold')
            
            with open(self.corpus_path, 'ab') as f:
                for doc in tqdm_asyncio.as_completed([scraper.get_doc(entry) for scraper, entry in missing_entries]):
                    doc = await doc

                    if doc:
                        f.write(encoder(doc))
                        f.write(b'\n')
            
            console.print('\nThe Corpus has been updated!', style='dark_cyan bold')