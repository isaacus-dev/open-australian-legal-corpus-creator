import os
import asyncio
import multiprocessing

import rich
import click

from platformdirs import user_data_dir
from rich.traceback import install

from .creator import Creator, SOURCES

# Use `uvloop` or `winloop` instead of `asyncio` if it's available.
try:
    from uvloop import run as async_run
    
except ImportError:
    try:
        from winloop import run as async_run
        
    except ImportError:
        from asyncio import run as async_run

# Setup traceback pretty printing with `rich` (suppressing full traceback for exceptions raised by `rich`, `click` and `asyncio`).
install(suppress=[rich, click, asyncio])

@click.command('mkoalc', context_settings={'help_option_names': ['-h', '--help']})
@click.version_option()
@click.option(
    '-s', '--sources',
    default=','.join(SOURCES.keys()),
    show_default=True,
    help='The names of the sources to be scraped, delimited by commas.',
)
@click.option(
    '-o', '--output',
    default=os.path.join(os.getcwd(), 'corpus.jsonl'),
    show_default=True,
    help='The path to the Corpus.',
)
@click.option(
    '-d', '--data_dir',
    default=os.path.join(os.getcwd(), user_data_dir('Open Australian Legal Corpus', 'Umar Butler')),
    show_default=True,
    help='The directory in which Corpus data should be stored.',
)
@click.option(
    '-n', '--num_threads',
    default=multiprocessing.cpu_count() - 1 or 1,
    show_default=True,
    help='The number of threads to use for OCRing PDFs with `tesseract`.',
)
@click.option(
    '-m', '--max-concurrent-ocr',
    default=1,
    show_default=True,
    help="The maximum number of PDFs that may be OCR'd concurrently",
)
def create(sources, output, data_dir, num_threads, max_concurrent_ocr):
    """The creator of the Open Australian Legal Corpus."""
    
    # Convert `sources` to a list of source names.
    sources = sources.split(',')
    
    # Create the Corpus.
    async_run(Creator(
        sources=sources,
        corpus_path=output,
        data_dir=data_dir,
        num_threads=num_threads,
        max_concurrent_ocr=max_concurrent_ocr,
    ).create())

if __name__ == '__main__':
    create()