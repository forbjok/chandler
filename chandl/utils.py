# -*- coding: utf-8 -*-

import os

def movefile(src, dst):
    if os.path.isfile(dst):
        os.remove(dst)

    os.rename(src, dst)
