"""Finding action files in a directory tree."""
from __future__ import annotations

from os import getcwd, walk
from os.path import abspath, join
from typing import List, Optional


def get_dir_files_as_list(dir_path: Optional[str] = None, default_search_file_extension: str = ".json") -> List[str]:
    """
    Every file under ``dir_path`` whose name ends with ``default_search_file_extension`` (lower-cased), as
    absolute paths in ``os.walk`` order. A missing directory gives an empty list.

    :param dir_path: the directory to search; ``None`` means the current directory when this is called.
    """
    search_root = getcwd() if dir_path is None else dir_path
    extension = default_search_file_extension.lower()
    return [abspath(join(root, file)) for root, _dirs, files in walk(search_root)
            for file in files if file.endswith(extension)]
