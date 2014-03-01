# -*- coding: utf-8 -*-

from collections import OrderedDict

class ChanHelper(object):
	THREAD_CLASS = 'thread'
	POST_CLASS = 'postContainer'

	def __init__(self, soup):
		self.soup = soup
		self.posts = {}

	def get_thread(self):
		try:
			return self.thread
		except AttributeError:
			t = self.soup.find('div', {'class' : self.THREAD_CLASS})
			self.thread = t
			return t

	def get_post(self, id):
		try:
			return self.posts[id]
		except KeyError:
			p = self.get_thread().find('div', {'class' : self.POST_CLASS, 'id' : id})
			self.posts[id] = p
			return p

	def get_posts_after(self, id):
		return self.get_post(id).find_next_siblings('div', {'class' : self.POST_CLASS})

	def get_posts(self):
		posts = OrderedDict()
		for post in self.get_thread().find_all('div', {'class' : self.POST_CLASS}):
			id = post.attrs.get('id', None)
			posts[id] = post

		return posts

	def get_first_post(self):
		try:
			return self.op
		except AttributeError:
			t = self.get_thread().find('div', {'class' : self.POST_CLASS})
			self.op = t
			return t

	def insert_posts_after(self, id, newposts):
		insert_after = self.get_post(id)

		for np in newposts:
			insert_after.insert_after(np)
			insert_after = np

class TinyboardChanHelper(ChanHelper):
	POST_CLASS = 'post'

	def get_thread(self):
		try:
			return self.thread
		except AttributeError:
			t = self.soup.find('div', {'class' : self.POST_CLASS}).parent
			self.thread = t
			return t

	def insert_posts_after(self, id, newposts):
		insert_after = self.get_post(id)

		for np in newposts:
			br = self.soup.new_tag('br')
			insert_after.insert_after(br)
			br.insert_after(np)
			insert_after = np
