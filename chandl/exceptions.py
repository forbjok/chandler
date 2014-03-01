# -*- coding: utf-8 -*-

class ThreadHTTPError(Exception):
	def __init__(self, code, reason):
		self.code = code
		self.reason = reason

		super(ThreadHTTPError, self).__init__("HTTP Error: {0:d} {1:s}".format(self.code, self.reason))

class ThreadNotFound(Exception):
	pass

class ThreadNotModified(Exception):
	pass

class UnsupportedSite(Exception):
	pass

class NoSaveDir(Exception):
	pass

class CancelException(Exception):
	pass