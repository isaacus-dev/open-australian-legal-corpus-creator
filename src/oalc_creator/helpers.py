import re
import asyncio
import itertools

from typing import Any, Callable, Iterable, Generator
from datetime import datetime
from textwrap import dedent
from contextlib import suppress

import ftfy
import orjson
import msgspec

from rich.console import Console

console = Console()

NON_STANDARD_CONTROL_CHARS_RE = re.compile(r'[' + re.escape('\a\b\f\r\v') + ']')
START_OF_TEXT_THAT_IS_ONLY_WHITESPACE_FOLLOWED_BY_A_NEWLINE_RE = re.compile(r'^\s*\n')
END_OF_TEXT_THAT_IS_ONLY_WHITESPACE_PRECEDED_BY_A_NEWLINE_RE = re.compile(r'\n\s*$')

def log(func: Callable) -> Callable:
    """Log any arguments passed to a function when an exception arises."""
    
    ERROR_MESSAGE = """
    Function: {func.__name__}
    Error message: {e}
    Arguments: {args}
    Keyword arguments: {kwargs}
    """
    ERROR_MESSAGE = dedent(ERROR_MESSAGE)
    
    def sync_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        
        except Exception as e:  
            warning(ERROR_MESSAGE.format(
                func=func,
                e=e,
                args=args,
                kwargs=kwargs,
            ))
            
            raise e
    
    async def async_wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        
        except Exception as e:
            warning(ERROR_MESSAGE.format(
                func=func,
                e=e,
                args=args,
                kwargs=kwargs,
            ))
            
            raise e
    
    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

def save_json(path: str, content: Any, encoder: Callable[[Any], bytes] = msgspec.json.encode) -> None:
    """Save content as a json file."""
    
    with open(path, 'wb') as writer:
        writer.write(encoder(content))

def load_json(path: str, decoder: Callable[[bytes], Any] = orjson.loads) -> Any:
    """Load a json file."""
    
    with open(path, 'rb') as reader:
        return decoder(reader.read())

def load_jsonl(path: str, decoder: Callable[[bytes], Any] = orjson.loads) -> list:
    """Load a jsonl file."""
    
    with open(path, 'rb') as file:
        return [decoder(json) for json in file]

def save_jsonl(path: str, content: list, encoder: Callable[[Any], bytes] = msgspec.json.encode) -> None:
    """Save a list of objects as a jsonl file."""
    
    with open(path, 'wb') as file:
        for entry in content:
            file.write(encoder(entry))
            file.write(b'\n')

def warning(message: str) -> None:
    """Log a warning message."""
    
    console.print(f'\n:warning-emoji:  {message}', style='orange1 bold', emoji=True, soft_wrap=True)

def format_date(date: str) -> str:
    """Format an Australian date into the format 'YYYY-MM-DD'."""
    
    for fmt in {'%d %B %Y', '%d %b %Y'}:
        with suppress(ValueError):
            return datetime.strptime(date, fmt).strftime('%Y-%m-%d')
    
    return datetime.strptime(date, '%d/%m/%Y').strftime('%Y-%m-%d')

def clean_text(
    text: str,
    fix_encoding: bool = True,
    normalise_nbsp: bool = True,
    remove_non_standard_ccs: bool = True,
    remove_unnecessary_whitespace: bool = True,
) -> str:
    """Clean text."""
    
    # Fix encoding issues.
    if fix_encoding:
        text = ftfy.fix_text(text)
    
    # Remove non-breaking spaces.
    if normalise_nbsp:
        text = text.replace('\xa0', ' ')
    
    # Remove non-standard control characters.
    if remove_non_standard_ccs:
        text = NON_STANDARD_CONTROL_CHARS_RE.sub('', text)
    
    # Remove unnecessary whitespace.
    if remove_unnecessary_whitespace:
        # Remove whitespace from lines comprised entirely of whitespace.
        text = '\n'.join([re.sub(r'\s+$', '', line) for line in text.split('\n')])

        # If the text begins with a newline or a newline preceded by whitespace, remove it and any preceding whitespace.
        text = START_OF_TEXT_THAT_IS_ONLY_WHITESPACE_FOLLOWED_BY_A_NEWLINE_RE.sub('', text)

        # If the text ends with a newline or a newline succeeded by whitespace, remove it and any succeeding whitespace.
        text = END_OF_TEXT_THAT_IS_ONLY_WHITESPACE_PRECEDED_BY_A_NEWLINE_RE.sub('', text)
    
    return text

def batch_generator(iterable: Iterable, batch_size: int) -> Generator[list, None, None]:
    """Generate batches of the specified size from the provided iterable."""
    
    iterator = iter(iterable)
    
    for first in iterator:
        yield list(itertools.chain([first], itertools.islice(iterator, batch_size - 1)))