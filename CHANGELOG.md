## Changelog 🔄
All notable changes to the Open Australian Legal Corpus Creator will be documented here. This project adheres to [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.1] - 2025-05-25
### Fixed
- Updated the base url of the Federal Court of Australia database due to a internal change on their part, fixing [#4](https://github.com/isaacus-dev/open-australian-legal-corpus-creator/issues/4).

## [3.1.0] - 2025-03-10
## Added
- Updated the cleaning routine to remove all control characters from texts apart from newlines and tabs.
- Began fixing Unicode encoding errors with [`ftfy`](https://github.com/rspeer/python-ftfy).
- Started using [`winloop`](https://github.com/Vizonex/Winloop) instead of `asyncio` if it is already installed in order to speed up scraping on Windows.
- Began sending default Brave Browser headers with requests to ensure maximum compatibility with websites.

### Fixed
- Fixed a bug with the cleaning of texts that caused the insertion and removal of extra newlines.
- Fixed a bug that caused the scraping of documents from the Federal Register of Legislation and possibly the High Court of Australia to take an inordinate amount of time and fail extremely often due to the fact that multiple asynchronous requests can be made in a single `_get_doc()` call and, although semaphores were used for those requests, the semaphore should have been used for the `_get_doc()` call itself instead.
- Fixed a bug preventing the indexing of documents on the Western Australian Legislation database due to the fact that it is now possible for links to legislation in indices to contain query parameters (eg, https://www.legislation.wa.gov.au/legislation/statutes.nsf/law_a2089.html&view=consolidated used to just be https://www.legislation.wa.gov.au/legislation/statutes.nsf/law_a2089.html) thereby breaking the existing regex used to extract document IDs from such links.
- Reduced the maximum number of documents that can be returned by a search engine results page of the Federal Register of Legislation database from 500 to 100 as the FLR database now enforces that limit.
- Fixed a bug that prevented links to Word document versions of cases on the Federal Court of Australia database from being scraped due to the inclusion of a new `data-url` attribute that broke a regex used to extract the links.

### Changed
- Switched from [`alive-progress`](https://github.com/rsalmei/alive-progress) to [`tqdm`](https://github.com/tqdm/tqdm) for progress bars in order to speed up scraping.
- Increased default indices and index refresh intervals from one day to two weeks.
- Transferred the Open Australian Legal Corpus Creator to Isaacus.

## [3.0.4] - 2024-08-08
### Fixed
- Fixed the fact that, when the Creator was run, it would unnecessarily rewrite the entire Corpus in order to detect and remove duplicates, outdated documents and otherwise repair it (which caused excessive writes and overwore disks) by instead first reading the Corpus and then only overwriting it if found necessary as, although this can sometimes double read time, reading is much cheaper on SSDs (which most modern drives are) than writing ([#2](https://github.com/isaacus-dev/open-australian-legal-corpus-creator/issues/2)).

## [3.0.3] - 2024-08-05
### Fixed
- Fixed a bug preventing the scraping of documents from the NSW Legislation database that are stored as PDFs but are reported by the database's web server as being HTML files.

## [3.0.2] - 2024-08-04
### Fixed
- Fixed a bug that caused only the first volume of multivolume documents on the Federal Register of Legislation available in a HTML format to be scraped instead of all volumes.

## [3.0.1] - 2024-07-26
### Fixed
- Fixed a bug that caused the earliest versions of documents from the Federal Register of Legislation not available in a HTML format to be scraped instead of their latest versions.

## [3.0.0] - 2024-06-01
### Added
- Added the `date` field.
- Added the `mime` field for storing the original MIME type of documents.
- Began lightly cleaning texts.
- Introduced the `max_concurrent_ocr` argument to `Creator` and `-m`/`--max-concurrent-ocr` argument to `mkoalc` to limit the maximum number of PDFs that may be OCR'd concurrently.

### Changed
- Suffixed the ids of documents in the Western Australian legislation database with their version ids, delimited by a slash, in order to make it easier to track changes to documents.
- Started filtering out documents with texts that, after being cleaned and stripped of non-alphabetic characters, are less than 9 characters long.
- Replaced PDF text extraction via `pdfplumber` with OCR via `tesseract` and `tesserocr` as most PDFs were poorly OCR'd.

### Fixed
- Improved removal of empty and restricted decisions from the NSW Caselaw database by making existing keyword searches for 'Decision number not in use' and 'Decision restricted' case- and whitespace-insensitive.
- Fixed documents from the Western Australian legislation database never being updated due to the use of the last modified date of the status pages of documents as version ids when the last modified date remained constant for all pages by switching to use the XXH3 64-bit hexidecimal hash of the `main` element of the status pages as version ids.
- Fixed bug preventing the scraping of documents from the Tasmanian Legislation database due to the improper skipping of documents that contain the substring 'Content Not Found.' and also set the substring to skip on to 'Content Not Found' (without a period, as it is not used by the database).
- Ensured that warnings are raised when the only version of a document available from the Federal Register of Legislation is a DOC.
- Fixed a bug preventing the scraping of PDFs from the Federal Register of Legislation database.
- Fixed a bug causing roughly 5.3k documents to be missed from the Federal Register of Legislation database during indexing as a result of a likely bug in the database.

### Removed
- Removed unused `dict2inst` helper function that converted dictionaries to instances of classes.

## [2.0.0] - 2024-05-18
### Added
- Introduced the `when_scraped` field of documents.
- Started retrying requests when parsing errors are encountered to cope with servers being overloaded but returning successful status codes.
- Added support for Python 3.10 and 3.11.
- Began checking for and removing corrupted documents from the Corpus.

### Changed
- Switched from `attrs` and `orjson` to `msgspec` in order to speed up and simplify the serialisation and deserialisation of Corpus data.
- Reduced the semaphore limit for the NSW Caselaw and Federal Court of Australia database from 30 to 10 to avoid overloading it.
- Made minor micro-optimisations by replacing lambda functions with named functions.

### Fixed
- Skipped scraping web pages from the NSW Legislation database that contain the substring 'No fragments found.' due to a newly identified bug in the database (see, eg, https://legislation.nsw.gov.au/view/whole/html/inforce/2021-03-25/act-1944-031).
- Skipped scraping web pages from the Tasmanian Legislation database that contain the substring 'Content Not Found.' due to a newly identified bug in the database (see, eg, https://www.legislation.tas.gov.au/view/whole/html/inforce/current/act-2022-033).
- Fixed a bug wherein documents from the Federal Register of Legislation database stored as DOC files were parsed as DOCX files by searching for PDF versions instead or otherwise skipping them.

## [1.0.1] - 2024-02-17
### Fixed
- Refactored the scraper for the Federal Register of Legislation database in order to resolve breaking API changes brought about by the database's redesign, thereby fixing [#1](https://github.com/isaacus-dev/open-australian-legal-corpus-creator/issues/1).

## [1.0.0] - 2023-11-09
### Added
- Created a scraper for the High Court of Australia database.
- Added status code `429` as a default retryable status code.

### Changed
- Improved performance.
- Expanded the maximum number of seconds to wait between retries.
- Expanded the maximum number of seconds that can be waited between retries before raising an exception.

## [0.2.0] - 2023-11-02
### Added
- Created a scraper for the NSW Caselaw database.

### Changed
- Sped up the parsing of PDFs from the Queensland Legislation database.

## [0.1.2] - 2023-10-30
### Fixed
- Fixed a bug where everything after the first occurance of a document's abbreviated jurisdiction was stripped from its citation by switching to searching for abbreviated jurisdictions enclosed in parentheses.

## [0.1.1] - 2023-10-30
### Fixed
- Fixed import error in the scraper for the Federal Court of Australia database.

## [0.1.0] - 2023-10-29
### Added
- Created this changelog.
- Adopted Semantic Versioning.
- Created a command-line interface for the Creator named `mkoalc`.
- Created a Python package for the Creator named `oalc_creator`.
- Introduced the `version_id` field of documents.
- Added support for the extraction of text from PDFs and DOCXs.
- Added support for documents from the Federal Register of Legislation stored as RTFs.
- Added support for documents from the Federal Court of Australia encoded as Windows-1252.
- Added support for documents from the Federal Court of Australia that were encoded incorrectly by extracting text from their DOCX versions.
- Automated the removal of incompatible Corpus data.

### Changed
- Switched from mulithreading to asyncio.
- Switched to object-oriented programming.
- Moved the `text` field of documents to the end.
- Switched to collecting documents from the South Australian Legislation database by scraping it instead of using database dumps.
- Switched from updating the Corpus by redownloading all documents to updating only the documents that have changed.

### Removed
- Removed the `open_australian_legal_corpus_creator.py` creator script.
- Removed [history notes](https://legislation.nsw.gov.au/help/inlinehistorynotes) from texts.

### Fixed
- Better preserved indentation in texts.
- Reduced excessive line breaks in texts.
- Improved the extraction and cleaning of citations.

[3.1.1]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v3.1.0...v3.1.1
[3.1.0]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v3.0.4...v3.1.0
[3.0.4]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v3.0.3...v3.0.4
[3.0.3]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v3.0.2...v3.0.3
[3.0.2]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v3.0.1...v3.0.2
[3.0.1]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v1.0.1...v2.0.0
[1.0.1]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v0.1.2...v1.0.0
[0.1.2]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/isaacus-dev/open-australian-legal-corpus-creator/releases/tag/v0.1.0