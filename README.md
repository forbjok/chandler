# Chandler

Chandler is a commandline-based thread downloader for imageboards.
It was primarily written with 4chan in mind, but also supports various other imageboards such as MLPchan, ylilauta and pretty much any Tinyboard-based chan.
Support for others should be easy to add in the future.

For some boards (4chan, MLPchan and Tinyboard currently), merging is supported, meaning that instead of simply overwriting the HTML every time the thread is updated, new posts will be merged into the existing HTML.
The advantage of this is that if posts are deleted from the thread, they will remain in the saved thread, assuming they were downloaded before they were deleted.

## Requirements
The following is required in order to run chandler:

* [Python 2.7](http://www.python.org/)
* [requests](https://pypi.python.org/pypi/requests)
* [html5lib](https://pypi.python.org/pypi/html5lib)
* [BeautifulSoup 4](https://pypi.python.org/pypi/beautifulsoup4)

Depending on your platform, there may be a number of ways to install the python modules, but the recommended way is to use **pip**.

How to install pip is beyond the scope of this readme, so for that check out the instructions at: <http://www.pip-installer.org/en/latest/installing.html>

Once pip is installed and working, the python modules can be installed by running:
```
$ pip install requests
$ pip install html5lib
$ pip install beautifulsoup4
```

## Getting Started
First, make sure everything listed under requirements is installed and working.

* Clone the repository: `git clone https://github.com/forbjok/chandler.git`
* Change into the repository's working directory.

To simply download a thread:
```
$ ./chandler.py -d threads http://boards.4chan.org/BOARD/thread/THREAD
```
... where "threads" is the name of the directory to download to.
Subdirectories will automatically be created per site, board and thread number.

To download a thread and then continue to check it for updates every 60 seconds:
```
$ ./chandler.py -d threads -c -i 60 http://boards.4chan.org/BOARD/thread/THREAD
```
... where `-c` means continuous, and `-i 60` specifies the interval between each check in seconds (in this case 60).

To download multiple threads:
```
$ ./chandler.py -d threads http://boards.4chan.org/BOARD/thread/THREAD http://boards.4chan.org/BOARD/thread/ANOTHER_THREAD
```
This way, any number of threads can be specified for download.
If multiple threads are specified, `-c` will be ignored.

## License
This project is licensed under the terms of the [MIT license](http://opensource.org/licenses/MIT).
