from setuptools import setup, find_packages

setup(
    name="rocksdbserver",
    version='0.1.3',
    description="RocksDB Server",
    keywords='rocksdbserver rocksdb',
    author='Prashanth Ellina',
    author_email="Use the github issues",
    url="https://github.com/deep-compute/rocksdbserver",
    license='MIT License',
    install_requires=[
        'cython >= 0.20',
        'decorator',
        'gevent',
        'decorator',
        'tornado',
        'msgpack-python',
        'funcserver',
        'pyrocksdb',
    ],
    dependency_links=[
        'https://github.com/deep-compute/funcserver/archive/master.zip#egg=funcserver',
        'http://github.com/stephan-hof/pyrocksdb/archive/v0.2.tar.gz#egg=pyrocksdb'
    ],
    package_dir={'rocksdbserver': 'rocksdbserver'},
    packages=find_packages('.'),
    include_package_data=True
)
