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
