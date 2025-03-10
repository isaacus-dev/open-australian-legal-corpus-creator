# Open Australian Legal Corpus Creator
<a href="https://github.com/umarbutler/open-australian-legal-corpus-creator" alt="Release"><img src="https://img.shields.io/badge/release-v3.1.0-green"></a>

The [Open Australian Legal Corpus](https://huggingface.co/datasets/umarbutler/open-australian-legal-corpus) is the first and only multijurisdictional open corpus of Australian legislative and judicial documents. This repository contains the code used to create and update the Corpus.

To learn more about the Corpus and how it was built, please see Umar Butler's article, [*How I built the largest open database of Australian law*](https://umarbutler.com/how-i-built-the-largest-open-database-of-australian-law/). If you're looking to download the Corpus, you may do so on [Hugging Face](https://huggingface.co/datasets/umarbutler/open-australian-legal-corpus).

## Requirements
The Open Australian Legal Corpus Creator requires Python 3.10 or higher, along with [`tesserocr`](https://github.com/sirfz/tesserocr).

Windows users have the option of installing [`winloop`](https://github.com/Vizonex/Winloop), the Windows port of [`uvloop`](https://github.com/MagicStack/uvloop) (which is automatically installed for Linux users), in order to speed up downloads.

Before running the Creator, it is **essential** that you are authorised to scrape and use the sources' data.

## Installation
Install [`tesserocr`](https://github.com/sirfz/tesserocr) by following the instructions [here](https://github.com/sirfz/tesserocr?tab=readme-ov-file#installation) and then run the following command:
```bash
pip install git+https://github.com/umarbutler/open-australian-legal-corpus-creator
```

## Usage
To create or update the Corpus, simply call `mkoalc` from the command line. By default, this will output the Corpus to a file named `corpus.jsonl` in the current working directory. Checkpoints and other Corpus data will be stored in your user data directory.

The Creator's default behaviour may be modified by passing the following optional arguments to `mkoalc`:
* `-s`/`--sources`: The names of the sources to be scraped, delimited by commas. Possible sources are `federal_court_of_australia`, `federal_register_of_legislation`, `high_court_of_australia`, `nsw_legislation`, `nsw_caselaw`, `queensland_legislation`, `south_australian_legislation`, `western_australian_legislation` and `tasmanian_legislation`. Defaults to all supported sources.
* `-o`/`--output`: The path to the Corpus. Defaults to a file named `corpus.jsonl` in the current working directory.
* `-d`/`--data_dir`: The path to the directory in which Corpus data should be stored. Defaults to the user's data directory as determined by [`platformdirs.user_data_dir`](https://github.com/platformdirs/platformdirs#the-problem) (on Windows, this will be `C:/Users/<username>/AppData/Local/Umar Butler/Open Australian Legal Corpus`).
* `-n`/`--num_threads`: The number of threads to use for OCRing PDFs with `tesseract`. Defaults to the number of logical CPUs on the system minus one, or one if there is only one logical CPU.
* `m`/`--max-concurrent-ocr`: The maximum number of PDFs that may be OCR'd concurrently. Defaults to 1.

As an example, if you wanted to output the Corpus to `~/corpus/oalc.jsonl`, save Corpus data to `~/app_data/oalc/` and scrape only the Federal Court of Australia and Federal Register of Legislation, you would run:
```bash
mkoalc -s federal_court_of_australia,federal_register_of_legislation -o ~/corpus/oalc.jsonl -d ~/app_data/oalc/
```

For even greater control over the Creator's behaviour, you may also access it from the `oalc_creator` Python package:
```python
from asyncio import run as async_run # or, if on Linux, `from uvloop import run as async_run`.
from oalc_creator import Creator

# Create a Creator instance.
creator = Creator(
    sources=['federal_court_of_australia', 'federal_register_of_legislation'],
    corpus_path='~/corpus/oalc.jsonl',
    data_dir='~/app_data/oalc/',
)

# Create or update the Corpus.
async_run(creator.create()) # `await creator.create()` if you are already in an event loop (eg, in a Jupyter notebook).
```

By creating your own subclasses of `oalc_creator.Scraper` and then passing them to `oalc_creator.Creator` as the `sources` argument, you can add support for custom sources. Examples of scrapers are available in [`src/oalc_creator/scrapers`](src/oalc_creator/scrapers). You are encouraged to contribute scrapers for new sources via pull requests.

## Licence
The Creator is licensed under the [MIT License](LICENCE).