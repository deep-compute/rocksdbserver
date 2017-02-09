from gevent import monkey; monkey.patch_all()

import os
import time
import uuid
import resource
import random
import string
import shutil
from inspect import getcallargs

import gevent
import msgpack
import rocksdb
from decorator import decorator
from funcserver import Server, Client, BaseHandler

ITERATOR_EXPIRY_CHECK = 5 * 60 # 5 minutes
ITERATOR_EXPIRE = 15 * 60 # 15 minutes
MAX_OPEN_FILES = 500000
ALPHANUM = string.letters + string.digits

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


def gen_random_seq(length=10):
    return ''.join([random.choice(ALPHANUM) for i in xrange(length)])


@decorator
def ensuretable(fn, self, table, *args, **kwargs):
    if table not in self.tables:
        raise Exception('Table "%s" does not exist' % table)
    return fn(self, self.tables[table], *args, **kwargs)


@decorator
def ensureiter(fn, self, _iter, *args, **kwargs):
    if _iter not in self.iters:
        raise Exception('Iter "%s" does not exist' % _iter)

    _iter = self.iters[_iter]
    _iter.ts_last_activity = time.time()
    return fn(self, _iter, *args, **kwargs)


@decorator
def ensurenewiter(fn, self, *args, **kwargs):
    name = getcallargs(fn, *args, **kwargs)['name'] or gen_random_seq()
    if args: args = list(args); args[0] = name
    else: kwargs['name'] = name

    if name in self.iters:
        raise Exception('iter "%s" exists already!' % name)

    return fn(self, *args, **kwargs)


class Iterator(object):
    NUM_RECORDS = 1000

    def __init__(self, table, type='items', reverse=False):
        '''
        @type: str; can be items/keys/values
        '''
        self.table = table
        self.type = type
        self.reverse = reverse
        self.ts_last_activity = time.time()

        iterfn = getattr(self.table.rdb,
            {'keys': 'iterkeys', 'values': 'itervalues'}\
            .get(type, 'iteritems'))

        self._iter = iterfn()

        if reverse:
            self._iter = reversed(self._iter)

    def get(self, num=NUM_RECORDS):
        records = []

        for record in self._iter:
            if self.type == 'items':
                key, item = record
                item = self.table.unpackfn(item)
                record = (key, item)
            elif self.type == 'values':
                record = self.table.unpackfn(record)

            records.append(record)
            if len(records) >= num: break

        return records

    def seek(self, key):
        self._iter.seek(key)

    def seek_to_first(self):
        return self._iter.seek_to_first()

    def seek_to_last(self):
        return self._iter.seek_to_last()


class Table(object):
    NAME = 'noname'
    ITER = Iterator

    KEYFN = staticmethod(lambda item: uuid.uuid1().hex)
    PACKFN = staticmethod(msgpack.packb)
    UNPACKFN = staticmethod(msgpack.unpackb)
    STATS_DUMP_PERIOD_SEC = 60 # 60 seconds

    def __init__(self, data_dir, db):
        self.data_dir = os.path.join(data_dir, self.NAME)
        self.rdb = self.open()
        self.db = db
        self.iters = {}

        self.keyfn = self.KEYFN
        self.packfn = self.PACKFN
        self.unpackfn = self.UNPACKFN
        self.iter_klass = self.ITER

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
        self.iters = {}
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

    # Iteration

    def list_keys(self):
        _iter = self.rdb.iterkeys()
        _iter.seek_to_first()
        return list(_iter)

    def list_values(self):
        _iter = self.rdb.itervalues()
        _iter.seek_to_first()
        return list(self.unpackfn(x) for x in _iter)

    @ensurenewiter
    def iter_keys(self, name=None, reverse=False):
        self.iters[name] = self.iter_klass(self, type='keys', reverse=reverse)
        return name

    @ensurenewiter
    def iter_values(self, name=None, reverse=False):
        self.iters[name] = self.iter_klass(self, type='values', reverse=reverse)
        return name

    @ensurenewiter
    def iter_items(self, name=None, reverse=False):
        self.iters[name] = self.iter_klass(self, type='items', reverse=reverse)
        return name

    def list_iters(self):
        return self.iters.keys()

    def close_iter(self, _iter):
        del self.iters[_iter]

    @ensureiter
    def iter_get(self, _iter, num=Iterator.NUM_RECORDS):
        return _iter.get(num)

    @ensureiter
    def iter_seek(self, _iter, key):
        return _iter.seek(key)

    @ensureiter
    def iter_seek_to_first(self, _iter):
        return _iter.seek_to_first()

    @ensureiter
    def iter_seek_to_last(self, _iter):
        return _iter.seek_to_last()

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

    # Iteration API methods

    @ensuretable
    def iter_keys(self, table, name=None, reverse=False):
        return table.iter_keys(name=name, reverse=reverse)

    @ensuretable
    def iter_values(self, table, name=None, reverse=False):
        return table.iter_values(name=name, reverse=reverse)

    @ensuretable
    def iter_items(self, table, name=None, reverse=False):
        return table.iter_items(name=name, reverse=reverse)

    @ensuretable
    def list_iters(self, table):
        return table.list_iters()

    @ensuretable
    def close_iter(self, table, name):
        return table.close_iter(name)

    @ensuretable
    def iter_get(self, table, name, num=Iterator.NUM_RECORDS):
        return table.iter_get(name, num)

    @ensuretable
    def iter_seek(self, table, name, key):
        return table.iter_seek(name, key)

    @ensuretable
    def iter_seek_to_first(self, table, name):
        return table.iter_seek_to_first(name)

    @ensuretable
    def iter_seek_to_last(self, table, name):
        return table.iter_seek_to_last(name)

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

    def expire_iters(self, api):
        while 1:
            ts = time.time()
            for table in api.tables.itervalues():
                expired = []

                for iter_name, _iter in table.iters.iteritems():
                    if ts - _iter.ts_last_activity >= ITERATOR_EXPIRE:
                        expired.append(iter_name)

                for iter_name in expired:
                    table.close_iter(iter_name)

            time.sleep(ITERATOR_EXPIRY_CHECK)

    def prepare_api(self):
        super(RocksDBServer, self).prepare_api()
        api = RocksDBAPI(self.args.data_dir)
        self.thread_expire_iters = gevent.spawn(self.expire_iters, api)
        return api

    def define_args(self, parser):
        super(RocksDBServer, self).define_args(parser)
        parser.add_argument('data_dir', type=str, metavar='data-dir',
            help='Directory path where data is stored')

class RocksDBClient(Client):

    def _iter(self, table, reverse, fn, prefix=None):
        fn = getattr(self, fn)
        name = fn(table, reverse=reverse)

        if prefix is None:
            if reverse:
                self.iter_seek_to_last(table, name)
            else:
                self.iter_seek_to_first(table, name)

        else:
            self.iter_seek(table, name, prefix)

        while 1:
            items = self.iter_get(table, name)
            if not items: break

            for item in items:
                yield item

        self.close_iter(table, name)

    def iterkeys(self, table, reverse=False):
        return self._iter(table, reverse, 'iter_keys')

    def itervalues(self, table, reverse=False):
        return self._iter(table, reverse, 'iter_values')

    def iteritems(self, table, reverse=False):
        return self._iter(table, reverse, 'iter_items')

if __name__ == '__main__':
    RocksDBServer().start()
