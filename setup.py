from setuptools import setup, find_packages
import os

HERE = os.path.abspath(os.path.dirname(__file__))
def get_long_description():
    dirs = [ HERE ]
    if os.getenv("TRAVIS"):
        dirs.append(os.getenv("TRAVIS_BUILD_DIR"))

    long_description = ""

    for d in dirs:
        rst_readme = os.path.join(d, "README.rst")
        if not os.path.exists(rst_readme):
            continue

        with open(rst_readme) as fp:
            long_description = fp.read()
            return long_description

    return long_description

long_description = get_long_description()

version = '0.1.3'
setup(
    name="rocksdbserver",
    version=version,
    description="RocksDB Server",
    long_description=long_description,
    keywords='rocksdbserver rocksdb',
    author='Deep Compute, LLC',
    author_email="contact@deepcompute.com",
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
    package_dir={'rocksdbserver': 'rocksdbserver'},
    packages=find_packages('.'),
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 2.7",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
    ]
)
