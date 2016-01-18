#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import os
import filecmp

import pytest
import httpretty

import chandl

"""Read and return the content of a file"""
def read_file(filename):
    with open(filename) as f:
        return f.read()

"""Set up fake URLs in httpretty based on a thread directory"""
def mock_thread(url, filename):
    dir, name = os.path.split(filename)

    httpretty.register_uri(httpretty.GET, url, body=read_file(filename + '.original'))

    filesdir = os.path.join(dir, 'files')
    for root, dirs, files in os.walk(filesdir):
        relroot = os.path.relpath(root, filesdir)
        for file in files:
            httpretty.register_uri(httpretty.GET, 'http://{0:s}'.format(os.path.join(relroot, file)), body=read_file(os.path.join(root, file)))

"""Assert that two directories compared with filecmp.dircmp() are identical"""
def assert_identical(dircmp):
    assert len(dircmp.right_only) == 0 and len(dircmp.diff_files) == 0

    for subdircmp in dircmp.subdirs.values():
        assert_identical(subdircmp)

"""Convenience class for enabling HTTPretty"""
class HTTPrettify(object):
    def __enter__(self):
        httpretty.reset()
        httpretty.enable()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        httpretty.disable()
        httpretty.reset()

def test_4chan_simple(tmpdir):
    savedir = tmpdir.mkdir('savedir')

    with HTTPrettify():
        mock_thread('http://boards.4chan.org/g/thread/39894014', 'testdata/4chan-simple/39894014.html')
        downloader = chandl.ThreadDownloader('http://boards.4chan.org/g/thread/39894014', str(savedir), None)
        downloader.download()

    threaddir = savedir.join('boards.4chan.org', 'g', '39894014')
    dircmp = filecmp.dircmp(str(threaddir), 'testdata/4chan-simple')
    assert_identical(dircmp)
