# -*- coding: utf-8 -*-

import re

class NullPostProcessor(object):
	def process_document(self, soup):
		pass
	def process_new_posts(self, posts):
		pass

class MLPChanPostProcessor(object):
	MATURE_THREAD_CLASS = 'mature_thread'
	MATURE_WARNING_CLASS = 'mature_warning'
	MATURE_SRC_TAG = 'data-mature-src'

	def process_document(self, soup):
		# Get rid of the terrible default stylesheet, so it reverts to Yotsuba B
		tag = soup.find('link', {'id' : 'stylesheet'})
		if tag != None:
			tag.decompose()

		# Remove mature warning
		tag = soup.find('div', {'class' : self.MATURE_WARNING_CLASS})
		if tag != None:
			tag.decompose()

		# Make thread visible even if it is marked as mature
		tag = soup.find('div', {'class' : self.MATURE_THREAD_CLASS})
		if tag != None:
			tag['style'] = 'display:inline'

	def process_new_posts(self, posts):
		for post in posts:
			# Change mature-spoilered thumbnails to the real thumbnails
			for tag in post.find_all('img', {'class' : 'postimg', self.MATURE_SRC_TAG : True}):
				tag['src'] = tag[self.MATURE_SRC_TAG]
