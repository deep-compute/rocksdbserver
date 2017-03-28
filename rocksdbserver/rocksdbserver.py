import os
import re
import time
import uuid
import resource
import shutil
import requests
import msgpack
import rocksdb
from decorator import decorator
from funcserver import Server, Client, BaseHandler

MAX_OPEN_FILES = 500000

def make_staticprefix(name, size):
    class StaticPrefix(rocksdb.interfaces.SliceTransform):
        '''
        Static prefix extractor implementation for pyrocksdb
        '''
        def name(self):
            return name

        def transform(self, src):
            return (0, size)

        def in_domain(self, src):
            return len(src) >= size

        def in_range(self, dst):
            return len(dst) == size

    return StaticPrefix()

class AttrDict(dict):
    '''
    A dictionary with attribute-style access. It maps attribute access to
    the real dictionary.

    # from: http://code.activestate.com/recipes/473786-dictionary-with-attribute-style-access/
    '''

    def __init__(self, init={}):
        dict.__init__(self, init)

    def __getstate__(self):
        return self.__dict__.items()

    def __setstate__(self, items):
        for key, val in items:
            self.__dict__[key] = val

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, dict.__repr__(self))

    def __setitem__(self, key, value):
        return super(AttrDict, self).__setitem__(key, value)

    def __getitem__(self, name):
        item = super(AttrDict, self).__getitem__(name)
        return AttrDict(item) if isinstance(item, dict) else item

    def __delitem__(self, name):
        return super(AttrDict, self).__delitem__(name)

    __getattr__ = __getitem__
    __setattr__ = __setitem__

    def copy(self):
        ch = AttrDict(self)
        return ch


@decorator
def ensuretable(fn, self, table, *args, **kwargs):
    if table not in self.tables:
        raise Exception('Table "%s" does not exist' % table)
    return fn(self, self.tables[table], *args, **kwargs)


class Table(object):
    NAME = 'noname'

    KEYFN = staticmethod(lambda item: uuid.uuid1().hex)
    PACKFN = staticmethod(msgpack.packb)
    UNPACKFN = staticmethod(msgpack.unpackb)
    STATS_DUMP_PERIOD_SEC = 60 # 60 seconds

    def __init__(self, data_dir, db):
        self.data_dir = os.path.join(data_dir, self.NAME)
        self.rdb = self.open()
        self.db = db

        self.keyfn = self.KEYFN
        self.packfn = self.PACKFN
        self.unpackfn = self.UNPACKFN

    def __str__(self):
        return '<Table: %s>' % self.NAME

    def __unicode__(self):
        return str(self)

    @property
    def log(self): return self.db.log

    def open(self):
        opts = self.define_options()
        opts.create_if_missing = True
        return rocksdb.DB(self.data_dir, opts)

    def close(self):
        del self.rdb

    def define_options(self):
        opts = rocksdb.Options()
        opts.stats_dump_period_sec = self.STATS_DUMP_PERIOD_SEC
        return opts

    def put(self, key, item, batch=None,
            keyfn=None, packfn=None):

        packfn = packfn or self.packfn
        keyfn = keyfn or self.keyfn

        db = batch or self.rdb

        if isinstance(item, dict):
            key = key or item.get('_id', None) or keyfn(item)
            item['_id'] = key
        else:
            key = key or keyfn(item)

        value = packfn(item)
        db.put(key, value)

        return key

    def get(self, key, unpackfn=None):
        unpackfn = unpackfn or self.unpackfn

        value = self.rdb.get(key)
        if value is None: return None

        item = unpackfn(value)
        return item

    def delete(self, key, batch=None):
        db = batch or self.rdb
        db.delete(key)

    def put_many(self, data):
        batch = rocksdb.WriteBatch()
        for key, item in data:
            self.put(key, item, batch=batch)
        self.rdb.write(batch)

    def get_many(self, keys):
        data = self.rdb.multi_get(keys)
        for key, value in data.iteritems():
            data[key] = None if value is None else msgpack.unpackb(value)
        return data

    def delete_many(self, keys):
        batch = rocksdb.WriteBatch()
        for key in keys:
            self.delete(key, batch=batch)
        self.rdb.write(batch)

    def delete_all(self):
        self.close()
        shutil.rmtree(self.data_dir)
        self.rdb = self.open()

    def count(self):
        _iter = self.rdb.iterkeys()
        _iter.seek_to_first()
        index = -1
        for index, k in enumerate(_iter): pass
        return index + 1

    def list_keys(self):
        _iter = self.rdb.iterkeys()
        _iter.seek_to_first()
        return list(_iter)

    def list_values(self):
        _iter = self.rdb.itervalues()
        _iter.seek_to_first()
        return list(self.unpackfn(x) for x in _iter)


    def _configure_iterator(self, iterator, seek_to=None, reverse=False):
        """
        configures the iterator by seeking to the right position and
        reversing if required.
        """
        if seek_to is not None:
            iterator.seek(seek_to)
        elif not reverse:
            iterator.seek_to_first()
        else:
            iterator.seek_to_last()

        if reverse:
            iterator = reversed(iterator)

        return iterator

    def iter_keys(self, seek_to=None, reverse=False, regex=None):
        """
        iterates through the keys in the database.
        `seek_to` - seeks to the given position if specified.
            defaults to the first record if reverse is False.
            defaults to the last record if reverse is True.

        `regex` - returns only keys that match the regex.
        """

        if regex is not None:
            regex = re.compile(regex)

        _iter = self.rdb.iterkeys()
        _iter = self._configure_iterator(_iter, seek_to=seek_to, reverse=reverse)
        for key in _iter:
            if regex is not None and not regex.match(key):
                continue

            yield key

    def iter_items(self, seek_to=None, reverse=False, regex=None):
        """
        iterates through the items in the database.
        `seek_to` - seeks to the given position if specified.
            defaults to the first record if reverse is False.
            defaults to the last record if reverse is True.

        `regex` - returns only items who's keys match the regex.
        """

        if regex is not None:
            regex = re.compile(regex)

        _iter = self.rdb.iteritems()
        _iter = self._configure_iterator(_iter, seek_to=seek_to, reverse=reverse)

        for (key, value) in _iter:
            if regex is not None and not regex.match(key):
                continue

            yield (key, self.unpackfn(value))

    def iter_values(self, seek_to=None, reverse=False, regex=None):
        """
        iterates through the values in the database.
        `seek_to` - seeks to the given position if specified.
            defaults to the first record if reverse is False.
            defaults to the last record if reverse is True.

        `regex` - returns only values who's keys match the regex.
        """

        item_iter = self.iter_items(seek_to=seek_to, reverse=reverse, regex=regex)
        for (key, value) in item_iter:
            yield value

    # Backup and restore

    def create_backup(self, path):
        backup = rocksdb.BackupEngine(path)
        return backup.create_backup(self.rdb, flush_before_backup=True)

    def stop_backup(self, path):
        backup = rocksdb.BackupEngine(path)
        return backup.stop_backup()

    def delete_backup(self, path, backup_id):
        backup = rocksdb.BackupEngine(path)
        return backup.delete_backup(backup_id)

    def get_backup_info(self, path):
        backup = rocksdb.BackupEngine(path)
        return backup.get_backup_info()

    def restore_backup(self, path, backup_id):
        backup = rocksdb.BackupEngine(path)
        return backup.restore_backup(backup_id, self.data_dir, self.data_dir)

    def restore_latest_backup(self, path):
        backup = rocksdb.BackupEngine(path)
        self.close()
        r = backup.restore_latest_backup(self.data_dir, self.data_dir)
        self.rdb = self.open()
        return r

    def purge_old_backups(self, path, num_backups_to_keep):
        backup = rocksdb.BackupEngine(path)
        self.close()
        r = backup.purge_old_backups(num_backups_to_keep)
        self.rdb = self.open()
        return r

    def dump(self, path, fmt=None, allow_coop=True):
        '''
        Dumps all table data into a file located at @path.
        @fmt (str): If specified (eg: "%(_id)s => %(url)s"),
            converts the record into a string based on the
            given format string.

            else, dumps the raw record as stored in table.
        @allow_coop (bool): if True, yields control
            every N iterations to allow for co-operative
            multi-tasking to work.
        '''
        f = open(path, 'wb')
        _iter = self.rdb.itervalues()
        _iter.seek_to_first()

        index = -1
        for index, v in enumerate(_iter):

            if fmt:
                r = self.unpackfn(v)
                for k, v in r.iteritems():
                    r[k] = AttrDict(v) if isinstance(v, dict) else v
                f.write('%s\n' % (fmt % r))
            else:
                f.write(v)

            if allow_coop and index % 100000 == 0: time.sleep(0)

        f.close()
        return index + 1

class RocksDBAPI(object):
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.tables = self.define_tables()

    def define_tables(self):
        return {}

    def list_tables(self):
        return self.tables.keys()

    @ensuretable
    def put(self, table, key, item):
        return table.put(key, item)

    @ensuretable
    def get(self, table, key):
        return table.get(key)

    @ensuretable
    def delete(self, table, key):
        return table.delete(key)

    @ensuretable
    def put_many(self, table, data):
        return table.put_many(data)

    @ensuretable
    def get_many(self, table, keys):
        return table.get_many(keys)

    @ensuretable
    def delete_many(self, table, keys):
        return table.delete_many(keys)

    @ensuretable
    def delete_all(self, table, allow_coop=True):
        '''
        Deletes all items from the table. Use with caution.
        If the table is very large, this could take a significant
        amount of time.
        '''
        return table.delete_all(allow_coop)

    @ensuretable
    def count(self, table):
        '''
        Count the number of records (kv pairs)
        '''
        return table.count()

    # TODO Iteration API methods
    @ensuretable
    def iter_keys(self, table, seek_to=None, reverse=False, regex=None):
        '''
        iterates through the keys in the table `table`.
        `seek_to` seeks to the given position if specified.
            - defaults to the first record if reverse is False.
            - defaults to the last record if reverse is True.

        `regex` - returns only keys that match the regex.
        '''
        keys_iter = table.iter_keys(
            seek_to=seek_to, reverse=reverse, regex=regex,
        )
        for key in keys_iter:
            yield key

    @ensuretable
    def iter_values(self, table, seek_to=None, reverse=False, regex=None):
        '''
        iterates through the values in the table `table`.
        `seek_to` - seeks to the given position if specified.
            defaults to the first record if reverse is False.
            defaults to the last record if reverse is True.

        `regex` - returns only values who's keys match the regex.
        '''
        values_iter = table.iter_values(
            seek_to=seek_to, reverse=reverse, regex=regex,
        )
        for value in values_iter:
            yield value

    @ensuretable
    def iter_items(self, table, seek_to=None, reverse=False, regex=None):
        '''
        iterates through the items in the table `table`..
        `seek_to` - seeks to the given position if specified.
            defaults to the first record if reverse is False.
            defaults to the last record if reverse is True.

        `regex` - returns only items who's keys match the regex.
        '''
        items_iter = table.iter_items(
            seek_to=seek_to, reverse=reverse, regex=regex,
        )
        for (key, value) in items_iter:
            yield (key, value)

    @ensuretable
    def list_keys(self, table):
        '''
        Lists all the keys in the table. This is meant
        to be used only during debugging in development
        and never in production as it loads all the keys
        in table into RAM which might cause memory load
        issues for large tables.
        '''
        return table.list_keys()

    @ensuretable
    def list_values(self, table):
        '''
        Lists all the values in the table. This is meant
        to be used only during debugging in development
        and never in production as it loads all the values
        in table into RAM which might cause memory load
        issues for large tables.
        '''
        return table.list_values()

    # Backup API methods

    @ensuretable
    def create_backup(self, table, path):
        return table.create_backup(path)

    @ensuretable
    def stop_backup(self, table, path):
        return table.stop_backup(path)

    @ensuretable
    def delete_backup(self, table, path, backup_id):
        return table.delete_backup(path, backup_id)

    @ensuretable
    def get_backup_info(self, table, path):
        return table.get_backup_info(path)

    @ensuretable
    def restore_backup(self, table, path, backup_id):
        return table.restore_backup(path, backup_id)

    @ensuretable
    def restore_latest_backup(self, table, path):
        return table.restore_latest_backup(path)

    @ensuretable
    def purge_old_backups(self, table, path, num_backups_to_keep):
        return table.purge_old_backups(path, num_backups_to_keep)

    @ensuretable
    def dump(self, table, path, fmt=None, allow_coop=True):
        return table.dump(path, fmt, allow_coop)

class RocksDBServer(Server):
    NAME = 'RocksDBServer'
    DESC = 'RocksDB Server'

    def __init__(self, *args, **kwargs):
        super(RocksDBServer, self).__init__(*args, **kwargs)

        # make data dir if not already present
        self.data_dir = os.path.abspath(self.args.data_dir)
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        self.set_file_limits()

    def set_file_limits(self):
        try:
            # ulimit -n unlimited
            resource.setrlimit(resource.RLIMIT_NOFILE,
                (MAX_OPEN_FILES, MAX_OPEN_FILES))
        except ValueError:
            self.log.warning('unable to increase num files limit. run as root?')

    def prepare_api(self):
        super(RocksDBServer, self).prepare_api()
        api = RocksDBAPI(self.args.data_dir)
        return api

    def define_args(self, parser):
        super(RocksDBServer, self).define_args(parser)
        parser.add_argument('data_dir', type=str, metavar='data-dir',
            help='Directory path where data is stored')

class RocksDBClient(Client):
    pass

if __name__ == '__main__':
    RocksDBServer().start()
