#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Get result from search engine and extract the data"""

from . import search
import multiprocessing
import hashlib
import json

from newspaper import Article
from newspaper.configuration import Configuration

__author__ = "Feryandi Nurdiantoro"

def extract(results):
  try:
    config = Configuration()
    config.fetch_images = False

    article = Article(results["url"], config=config)
    retry = 0    
    while not article.is_downloaded and retry < 3:
      article.download()
      retry += 1
    article.parse()
    text = ''.join([i if ord(i) < 128 else ' ' for i in str(article.text)])
    print("=", end='', flush=True)
    return (results["url"], results["title"], text, article.publish_date) 
  except Exception as e:
    print(e)
    return (results["url"], results["title"], None, None)

def get_articles(keyword):
  se = [search.bing(keyword), search.duckduckgo(keyword)]

  with multiprocessing.Pool(processes=2) as pool: 
    pool_outputs = pool.map(search.search, se)
    pool.close()
    pool.join()

  ret = []
  counter = 0
  checker = {}
  for results in pool_outputs:
    for result in results:
      if counter < 20:
        sha = hashlib.sha1(result["url"].rstrip().encode()).hexdigest()
        if sha not in checker:
          checker[sha] = True
          ret.append(result)
          counter += 1
  return ret

def search_all(keyword):
  ret = None
  results = get_articles(keyword) ## This took 2s ~ 10s
  print("Extracting: ", end='', flush=True)
  with multiprocessing.Pool(processes=8) as pool: 
    ret = pool.map(extract, results)
  print("\nFinish Extracting")
  return ret

if __name__== "__main__":
  import time
  start = time.time()

  keyword = "american vietnam military unite native supernatural state war recruit scout course"
  results = get_articles(keyword) ## This took 2s ~ 10s

  end = time.time()
  print("Elapsed: " + str(end-start))

  ret = None
  with multiprocessing.Pool(processes=8) as pool: 
    ret = pool.map(extract, results)

  print(ret)

  end = time.time()
  print("Elapsed: " + str(end-start))