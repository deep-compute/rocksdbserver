# rocksdbserver

A server exposing an RPC interface to RocksDB

## Installation

(original instructions from http://pyrocksdb.readthedocs.org/en/latest/installation.html)

### install librocksdb.so

``` bash
$ sudo apt-get install build-essential
$ sudo apt-get install python-virtualenv python-dev
$ sudo apt-get install libsnappy-dev zlib1g-dev libbz2-dev libgflags-dev
$ git clone https://github.com/facebook/rocksdb.git
$ cd rocksdb
$ # It is tested with this version
$ git checkout 3.9.fb
$ make shared_lib
$ sudo mv librocksdb.so /usr/lib/
$ sudo mv include/* /usr/include/
```

### Install RocksDBServer

``` bash
sudo pip install git+git://github.com/prashanthellina/rocksdbserver.git
```

## Usage

### Basic Usage

Consider this simple usage example from the examples/ directory.

``` python
from rocksdbserver import RocksDBServer, RocksDBAPI, Table

class NamesTable(Table):
    NAME = 'names'

class SimpleDBAPI(RocksDBAPI):
    def define_tables(self):
        names = NamesTable(self.data_dir, self)
        return {names.NAME: names}

class SimpleDBServer(RocksDBServer):
    NAME = 'SimpleDBServer'
    DESC = 'Simple DB Server based on RockDB Server'

    def prepare_api(self):
        return SimpleDBAPI(self.args.data_dir)

if __name__ == '__main__':
    SimpleDBServer()
```

The above code represents a database with just one table called 'names'. Run this server by doing

``` bash
python examples/simple_db.py run /tmp/data
```

The argument /tmp/data points to the data directory where the db files are stored. You can pick an alternate location too.

Now visit http://locahost:8889 to use the web based console and try out the following

![Image](./simpledb.png?raw=true)

The above exercise demonstrates how to interact with the database via a web based shell. Now let us try to interact with the database from a Pythons script using the client API.

Consider this sample client code from examples/simple_db_client.py

``` python
from rocksdbserver import RocksDBClient

if __name__ == '__main__':
    db = RocksDBClient('http://localhost:8889')
    print db.put('names', 'prashanth', {'last_name': 'ellina', 'days': 10})
    key = db.put('names', None, {'last_name': 'doe', 'days': 12})
    print key

    print db.get('names', 'prashanth')
    print db.get('names', key)
```

Run this by doing

``` bash
python examples/simple_db_client.py
```

The output will look something like this

``` bash
$ python simple_db_client.py 
prashanth
238b74b0af8d11e3bcd3d43d7e99b40b
{'last_name': 'ellina', 'days': 10, '_id': 'prashanth'}
{'last_name': 'doe', 'days': 12, '_id': '238b74b0af8d11e3bcd3d43d7e99b40b'}
```

### More details on usage

#### Deletion

``` python
> api.delete('names', 'prashanth')
> api.get('names', 'prashanth')

# In case you need to delete multiple keys at once, do
> api.delete('names', ['prashanth', '238b74b0af8d11e3bcd3d43d7e99b40b'])

# Let us add some data back
> api.put('names', None, {'last_name': 'ellina'})
> api.put('names', None, {'last_name': 'ellina1'})
> api.put('names', None, {'last_name': 'ellina2'})

> help(api.delete_all)
Help on method delete_all in module rocksdbserver.rocksdbserver:
 
delete_all(self, table, *args, **kwargs) method of __main__.SimpleDBAPI instance
    Deletes all items from the table. Use with caution.
    If the table is very large, this could take a significant
    amount of time.

> api.delete_all()
```

#### Iteration

The below session in the web-based console demonstrates iteration. Just like the exercise above the very same API commands used in the web-based console can be utilized from a client proxy.

``` python

# Let us first create some records

> api.put('names', None, {'city': 'London'})
'cc38f17ccca311e3aec5d43d7e99b40b'
 
> api.put('names', None, {'city': 'New York'})
'd0541de0cca311e3aec5d43d7e99b40b'
 
> api.put('names', None, {'city': 'Boston'})
'd32f14c0cca311e3aec5d43d7e99b40b'
 
> api.put('names', None, {'city': 'Frankfurt'})
'd5ce57d6cca311e3aec5d43d7e99b40b'
 
> api.put('names', None, {'city': 'Singapore'})
'd88c8acecca311e3aec5d43d7e99b40b'

> help(api.list_keys)
Help on method list_keys in module rocksdbserver.rocksdbserver:
 
list_keys(self, table, *args, **kwargs) method of __main__.SimpleDBAPI instance
    Lists all the keys in the table. This is meant
    to be used only during debugging in development
    and never in production as it loads all the keys
    in table into RAM which might cause memory load
    issues for large tables.
 
> api.list_keys('names')
['cc38f17ccca311e3aec5d43d7e99b40b', 'd0541de0cca311e3aec5d43d7e99b40b', 'd32f14c0cca311e3aec5d43d7e99b40b', 'd5ce57d6cca311e3aec5d43d7e99b40b', 'd88c8acecca311e3aec5d43d7e99b40b']

> help(api.list_values)
Help on method list_values in module rocksdbserver.rocksdbserver:
 
list_values(self, table, *args, **kwargs) method of __main__.SimpleDBAPI instance
    Lists all the values in the table. This is meant
    to be used only during debugging in development
    and never in production as it loads all the values
    in table into RAM which might cause memory load
    issues for large tables.
    
> api.list_values('names')
[{'city': 'London', '_id': 'cc38f17ccca311e3aec5d43d7e99b40b'}, {'city': 'New York', '_id': 'd0541de0cca311e3aec5d43d7e99b40b'}, {'city': 'Boston', '_id': 'd32f14c0cca311e3aec5d43d7e99b40b'}, {'city': 'Frankfurt', '_id': 'd5ce57d6cca311e3aec5d43d7e
99b40b'}, {'city': 'Singapore', '_id': 'd88c8acecca311e3aec5d43d7e99b40b'}]

# list_keys and list_values are for usage for testing and development. For production
# usage the following is the way to perform iteration.

> iterK = api.iter_keys('names')
> iterK
'NcYAzfks0z'
 
# iterK is a string that represents our current iterator whose state is maintained on the server.
 
> api.tables['names'].iters
{'NcYAzfks0z': <rocksdbserver.rocksdbserver.Iterator object at 0x7f98a8a03550>}

# Before beginning the iteration we need to set the cursor location by seeking.
# Let us seek to the beginning.
 
> api.iter_seek_to_first('names', iterK)

# Ask the API to send us the first two keys
> api.iter_get('names', iterK, num=2)
['cc38f17ccca311e3aec5d43d7e99b40b', 'd0541de0cca311e3aec5d43d7e99b40b']
 
# And two more
> api.iter_get('names', iterK, num=2)
['d32f14c0cca311e3aec5d43d7e99b40b', 'd5ce57d6cca311e3aec5d43d7e99b40b']

# And the more (only one is left now)
> api.iter_get('names', iterK)
['d88c8acecca311e3aec5d43d7e99b40b']
 
# There are no more keys left to iterate over.
> api.iter_get('names', iterK)
[]

# Cleanup the iterator state on the server
# The server will garbage collect eventually but it is a good
# practice to perform this action explicitly.
> api.close_iter('names', iterK)
> api.tables['names'].iters
{}
```

The above exercise shows how to iterate over keys using `iter_keys` API method. You can use `iter_values` for iteration over values and `iter_items` for iterating over key-value item pairs.

#### Client side iteration

``` python
# Let us first create some records

> api.put('names', None, {'city': 'London'})
'cc38f17ccca311e3aec5d43d7e99b40b'
 
> api.put('names', None, {'city': 'New York'})
'd0541de0cca311e3aec5d43d7e99b40b'
 
> api.put('names', None, {'city': 'Boston'})
'd32f14c0cca311e3aec5d43d7e99b40b'
 
> api.put('names', None, {'city': 'Frankfurt'})
'd5ce57d6cca311e3aec5d43d7e99b40b'
 
> api.put('names', None, {'city': 'Singapore'})
'd88c8acecca311e3aec5d43d7e99b40b'
```

Now consider this python script that demonstrates client side iteration.

``` python
from rocksdbserver import RocksDBClient

if __name__ == '__main__':
    db = RocksDBClient('http://localhost:8889')
    for key in db.iterkeys('names'):
        print key
```

You could do the same for values and item using `itervalues` and `iteritems` respectively. The client code uses `iter_keys`, `iter_values` and `iter_items` API methods internally.
