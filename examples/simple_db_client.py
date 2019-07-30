from rocksdbserver import RocksDBClient

if __name__ == '__main__':
    db = RocksDBClient('http://localhost:8889')
    print(db.put('names', 'prashanth', {'last_name': 'ellina', 'days': 10}))
    key = db.put('names', None, {'last_name': 'doe', 'days': 12})
    print(key)

    print(db.get('names', 'prashanth'))
    print(db.get('names', key))
