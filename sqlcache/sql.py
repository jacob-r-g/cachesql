import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union
from zipfile import ZipFile

import pandas as pd
from sqlalchemy import create_engine

from . import __version__
from .store import ParquetStore

logger = logging.getLogger(__name__)


class Database:
    """Database connector with caching functionality

    Generic class to connect to SQL databases. When querying DBs the results will
    be cached on a disk to speed up the next time the same query is done.

    Parameters
    ----------
    name
        Name of the database.
    uri
        URI string passed to SQLalchemy to connect to the database
    cache_store
        Path where cache should be stored
    normalize
        If True, normalize the queries to make the cache independent from formatting changes
    """

    def __init__(
        self,
        name: str,
        uri: str,
        cache_store: Union[str, Path] = None,
        normalize: bool = True,
    ):
        self.name = name
        cache_store = Path(cache_store or ".cache").absolute() / self.name
        self.cache = ParquetStore(
            cache_store=Path(cache_store),
            normalize=normalize,
        )
        self.engine = create_engine(uri, convert_unicode=True)
        self.session = set()

    def query(
        self, query: str, force: bool = False, cache: bool = True
    ) -> pd.DataFrame:
        """Query the database with cache functionality

        Parameters
        ----------
        query
            Query string to be sent to the database
        force
            If True, ignore existing cache if any. Useful when you want to refresh data
            on cache.
        cache
            If True, use cache mechanism. Otherwise, ignore existing cache and do not store
            in cache the results. Useful when used in production. In many situations you
            don't want to waist disk space with useless cache.

        Returns
        -------
        pd.DataFrame
            Results of the query
        """

        logger.info(f"Querying {self.name!r}")
        if self.cache.exists(query) and not (force or not cache):
            logger.info(f"Loading from cache.")
            results, metadata = self.cache.load(query)
            logger.info(
                f"The cached query was executed on the {metadata['executed_at']} "
                f"and lasted {timedelta(seconds=metadata['duration'])}s"
            )
        else:
            executed_at = datetime.now().isoformat()
            start_time = time.time()
            results = self._query(query)
            duration = time.time() - start_time
            logger.info(f"Finished in {timedelta(seconds=duration)}s")

            if cache:
                metadata = {
                    "db_name": self.name,
                    "sqlcache": __version__,
                    "username": self.engine.url.username or "unknown",
                    "executed_at": executed_at,
                    "duration": duration,
                }
                self.cache.dump(query, results, metadata)
                logger.info(f"Results have been stored in cache")

        self.session.add(query)
        return results

    def _query(self, query: str) -> pd.DataFrame:
        return pd.read_sql(sql=query, con=self.engine)

    def exists_in_cache(self, query: str) -> bool:
        """Return True if a given query has cached results"""
        return self.cache.exists(query)

    def export_session(self, filename: Union[str, Path]) -> None:
        """Export contents of cache obtained during this session to a zip file

        Used in conjunction with the :py:meth:`Store.import_cache <Store.import_cache>` method,
        you can share the cache of one specific coding session with your colleagues in order to
        guarantee reproducibility of your code and speed up collaboration. Or you can simply use
        it to migrate your cache from one environment to the other.

        Parameters
        ----------
        filename
            Path to a zip file where cache will be exported
        """
        self.cache.export(filename=filename, queries=self.session)
