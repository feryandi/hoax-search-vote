import logging
import json
import time
import sys

## ANALYZER
import uuid

from sklearn.externals import joblib

from helper import Similar
from helper import Searcher

from article import Article
from database import Database

class Analyzer:
	target = ['unrelated', 'fact', 'hoax', 'unknown']
	target_neg = ['unrelated', 'hoax', 'fact', 'unknown']

	def __init__(self, text, query, client=None, qneg=False, lang="en", qtype="undefined"):
		self.text = ''.join([i if ord(i) < 128 else ' ' for i in text])
		#self.query = query
		self.query = ' '.join(self.__query_unique_list(query.split()))
	
		self.client = client
		if not type(self.client) is dict:
			self.client = {}

		self.retrieved = None
		self.qneg = qneg
		self.qtype = qtype
		self.lang = lang
		self.db = Database()
	
	def _get_query_hoax(self):
		## TRying not using + Hoax query, maybe better?
		return self.query + ''

	def __query_unique_list(self, l):
	    ulist = []
	    [ulist.append(x) for x in l if x not in ulist]
	    return ulist

	def __do_voting(self, conclusion, sites):
		THRESHOLD_UNKNOWN = 0.35
		## Credible News
		if sites["cfact"] > 2 and sites["cfact"] > sites["choax"]: return 1
		if sites["choax"] > 2 and sites["choax"] > sites["cfact"]: return 2
		## Not credible News
		if sites["nfact"] > 2 and sites["choax"] != 0: return 2
		if sites["nhoax"] > 2 and sites["cfact"] != 0: return 1

		if (sites["tfact"] + sites["thoax"] + sites["tunk"] < 3): return 3
		if (abs(conclusion[1] - conclusion[2]) < 0.5): return 3
		if ((conclusion[1] == 0) and (not conclusion[2] == 0)):
			if (conclusion[2] < 2.5): return 3
			if(conclusion[2] >= (conclusion[3] - (conclusion[2]/2))): return 2
		if ((conclusion[2] == 0) and (not conclusion[1] == 0)):
			if (conclusion[1] < 2.5): return 3
			if(conclusion[1] >= (conclusion[3] - (conclusion[1]/2))): return 1
		if ((conclusion[3] + 2.5) > (conclusion[1] + conclusion[2])):
			return 3
		if (conclusion[2] >= conclusion[1]):
			if (conclusion[2] < 2): return 3
			if (conclusion[2] >= conclusion[1] * 2): return 2
			if (conclusion[2] > (conclusion[1] + conclusion[3])): return 2
			else:
				if ((conclusion[1] + conclusion[3]) - conclusion[2] < THRESHOLD_UNKNOWN): return 2
				else: return 3
		elif (conclusion[2] < conclusion[1]):
			if (conclusion[1] < 2): return 3
			if (conclusion[2] > conclusion[1] * 2): return 1
			if ((conclusion[3] + conclusion[2]) < conclusion[1]): return 1
			else:
				if ((conclusion[3] + conclusion[2]) - conclusion[1] < THRESHOLD_UNKNOWN): return 1
				else: return 3
		else: return 3

	def __calculate_weight(self, dataset):
		meta = sorted(dataset, key=lambda x: x.date, reverse=True)
		i = 0
		for a in meta:
			a.set_weight((((len(meta) - i) / float(len(meta))) * 0.5) + int(a.url_score) * 0.5)
			i += 1
		return dataset

	def __get_references(self, dataset, label):
		meta = sorted(dataset, key=lambda x: (x.date, x.url_score), reverse=True)
		selected = []
		for m in meta:
			if m.label == label:
				selected.append(m)	
		for m in meta:
			if m.label != label and m.label != 'unrelated':
				selected.append(m)	
		for m in meta:
			if m.label == 'unrelated':
				selected.append(m)
		return selected

	def __cleanup_dataset(self, dataset):
		checked = {}
		clean_dataset = []
		for article in dataset:
			url = article.url.rstrip()
			if "forum" not in article.url_base:
				if url not in checked:
					checked[url] = True
					clean_dataset.append(article)
		return clean_dataset

	def _get_conclusion(self, dataset):
		conclusion = [0] * 4
		sites = {}
		sites["tfact"] = 0
		sites["thoax"] = 0
		sites["tunk"] = 0
		sites["tunr"] = 0
		sites["cfact"] = 0
		sites["choax"] = 0
		sites["nfact"] = 0
		sites["nhoax"] = 0

		if len(dataset) > 2:
			dataset = self.__calculate_weight(dataset)

			sentences = []
			for article in dataset:
				sentences.append(article.content_clean[:550])

			# ATTETION HERE! CHANGE THE QUERY TO TEXT
			#similar = Similar(self._get_query_hoax(), sentences)
			similar = Similar(self.text, sentences)
			clf = joblib.load('./models/generated_model.pkl') 
			i = 0

			for num, result in similar.rank:
				article = dataset[num]
				article.set_similarity(result)
				article.count_query_appeared(self.text)

				counts = article.get_category_count()
				if article.similarity < 0.045:
					article.reason = "Similarity < 0.045"
					idx = 0
				elif len(article.content) < 400:
					article.reason = "Content < 400"
					idx = 3
				elif counts[0] >= 2 and counts[1] == 0:
					article.reason = "Rule 1 #1"
					idx = 2
				elif counts[1] >= 1 and counts[0] > counts[1] * 2.5:
					article.reason = "Rule 1 #2"
					idx = 2
				elif counts[0] >= 1 and counts[1] > counts[0] * 2.5:
					article.reason = "Rule 1 #3"
					idx = 1
				else:
					article.reason = "Model Fallback 1"
					idx = clf.predict([article.get_features_array()])[0]

				article.set_label(Analyzer.target[idx])
				conclusion[idx] += 1 + article.weight
				if idx == 1:
					sites["tfact"] += 1
					if article.url_score >= 2:
						sites["cfact"] += 1
					if article.url_score <= -2:
						sites["nfact"] += 1
				elif idx == 2:
					sites["thoax"] += 1
					if article.url_score >= 2:
						sites["choax"] += 1
					if article.url_score <= -2:
						sites["nhoax"] += 1
				elif idx == 3:
					sites["tunk"] += 1
				elif idx == 0:
					sites["tunr"] += 1
				i += 1

		return (conclusion, sites)

	def _get_alt_conclusion(self, dataset):
		conclusion = [0] * 4
		sites = {}
		sites["tfact"] = 0
		sites["thoax"] = 0
		sites["tunk"] = 0
		sites["tunr"] = 0
		sites["cfact"] = 0
		sites["choax"] = 0
		sites["nfact"] = 0
		sites["nhoax"] = 0

		if len(dataset) > 2:
			dataset = self.__calculate_weight(dataset)

			sentences = []
			for article in dataset:
				sentences.append(article.content_clean[:550])

			# ATTETION HERE! CHANGE THE QUERY TO TEXT
			#similar = Similar(self._get_query_hoax(), sentences)
			similar = Similar(self.text, sentences)
			clf = joblib.load('./models/generated_model.pkl') 
			i = 0

			for num, result in similar.rank:
				article = dataset[num]
				article.set_similarity(result)
				article.count_query_appeared(self.text)

				counts = article.get_category_count()
				if article.feature_query_percentage < 0.45:
					article.reason = "Rule 2 #1"
					idx = 0
				elif article.feature_query_percentage < 0.67 and article.similarity < 0.37:
					article.reason = "Rule 2 #2"
					idx = 3
				elif (article.similarity < 0.35) and (article.feature_query_count < 2):
					article.reason = "Rule 2 #3"
					idx = 0
				elif (article.similarity < 0.25) and (article.feature_query_count < 5):
					article.reason = "Rule 2 #4"
					idx = 0
				elif counts[1] == 0 and counts[0] == 0 and counts[3] < 20:
					article.reason = "Rule 2 #5"
					idx = 1
				elif counts[1] == 0 and counts[0] == 0 and counts[3] >= 20:
					article.reason = "Rule 2 #6"
					idx = 3
				else:
					article.reason = "Model Fallback 2"
					idx = clf.predict([article.get_features_array()])[0]

				article.set_label(Analyzer.target[idx])
				conclusion[idx] += 1 + article.weight
				if idx == 1:
					sites["tfact"] += 1
					if article.url_score >= 2:
						sites["cfact"] += 1
					if article.url_score <= -2:
						sites["nfact"] += 1
				elif idx == 2:
					sites["thoax"] += 1
					if article.url_score >= 2:
						sites["choax"] += 1
					if article.url_score <= -2:
						sites["nhoax"] += 1
				elif idx == 3:
					sites["tunk"] += 1
				elif idx == 0:
					sites["tunr"] += 1
				i += 1

		return (conclusion, sites)

	def _determine_result(self, dataset):
		conclusion, self.sites = self._get_conclusion(dataset)
		ridx = self.__do_voting(conclusion, self.sites)
		if ridx == 3: # If UNKNOWN
			conclusion, self.sites = self._get_alt_conclusion(dataset)
			ridx = self.__do_voting(conclusion, self.sites)
		return (conclusion, ridx)

	def recalculate_factcheck(self, factcheck):
		########################################
		##
		##  Number code meaning
		##
		##  0 : Unrelated
		##  1 : Hoax
		##  2 : Fact
		##  3 : Unknown
		##  7 : Hoax contained sentences
		##	8 : Neutral sentences, probably facts
		##
		########################################
		conclusion = self.conclusion

		if "code" in factcheck:
			negate = factcheck["is_negate"]
			if factcheck["code"] == 1:
				if not negate: conclusion[2] += 7
				else: conclusion[1] += 7
			if factcheck["code"] == 2:
				if not negate: conclusion[1] += 7
				else: conclusion[2] += 7
			if factcheck["code"] == 7:
				if not negate: conclusion[2] += 5
				else: conclusion[1] += 5
			if factcheck["code"] == 8:
				if not negate: conclusion[1] += 5
				else: conclusion[2] += 5

		self.ridx = self.__do_voting(conclusion, self.sites)
		self.conclusion = conclusion

		if self.qneg:
			self.conclusion = [self.conclusion[0], self.conclusion[2], self.conclusion[1], self.conclusion[3]]
			if self.ridx == 1:
				self.ridx = 2
			elif self.ridx == 2:
				self.ridx = 1
		return (self.conclusion, self.ridx)

	def result(self):
		return Analyzer.target[self.ridx]

	def init_retrieve(self, loghash):
		self.retrieved = self.db.get_query_by_loghash(loghash)
		if not self.retrieved == None:
			return self.retrieved["query_text"]
		return None

	def retrieve(self, loghash):
		query = self.retrieved
		if not query == None:
			self.query = query["query_search"]
			self.text = query["query_text"]
			self.qneg = query["query_negation"]
			s = Searcher(self.query)
			dataset = s.get_news(query["query_hash"])
			self.dataset = self.__cleanup_dataset(dataset)

			self.conclusion, self.ridx = self._determine_result(dataset)
			references = self.__get_references(dataset, Analyzer.target[self.ridx])

			lor = []
			for r in references:
				data = {}
				data["url"] = r.url
				data["url_base"] = r.url_base
				if not self.qneg:
					data["label"] = r.label
				else:
					if r.label == Analyzer.target[1]:
						data["label"] = Analyzer.target_neg[1]
					elif r.label == Analyzer.target[2]:
						data["label"] = Analyzer.target_neg[2]
					else:
						data["label"] = r.label
				data["text"] = r.content[:900] + "... (see more at source)"
				data["id"] = r.ahash
				data["site_score"] = r.url_score
				data["date"] = str(r.date)
				data["feature"] = str(r.get_humanize_feature())
				data["counts"] = str(r.get_category_count())
				data["reason"] = r.reason
				lor.append(data)

			result = {}
			result["is_neg"] = self.qneg
			result["inputText"] = query["query_text"]
			result["hash"] = query["query_hash"]
			result["query_search"] = query["query_search"]
			if not self.qneg:
				result["conclusion"] = Analyzer.target[self.ridx]
				result["scores"] = self.conclusion
			else:
				result["conclusion"] = Analyzer.target_neg[self.ridx]
				neg_concl = [self.conclusion[0], self.conclusion[2], self.conclusion[1], self.conclusion[3]]
				result["scores"] = neg_concl
			result["references"] = lor
			result["status"] = "Success"
			result["id"] = loghash

			self.db.insert_result_log(s.qid, self.conclusion[2], self.conclusion[1], self.conclusion[3], self.conclusion[0], result["conclusion"])
		else:
			result = {}
			result["status"] = "Failed"
			result["message"] = "Query not found"
		return result
		
	def do(self):
		dataset = []

		s = Searcher(self._get_query_hoax())

		if not "ip" in list(self.client.keys()):
			self.client["ip"] = "unknown"
		if not "browser" in list(self.client.keys()):
			self.client["browser"] = "unknown"

		query_uuid = uuid.uuid4().hex
		s.set_qid(self.db.insert_query_log(query_uuid, self.qtype, self.text, self.query, s.query_hash, self.client["ip"], self.client["browser"], self.qneg, self.lang))
		print("Search for all")
		dataset = s.search_all()
		self.dataset = self.__cleanup_dataset(dataset)

		self.conclusion, self.ridx = self._determine_result(dataset)
		references = self.__get_references(dataset, Analyzer.target[self.ridx])

		lor = []
		for r in references:
			data = {}
			data["url"] = r.url
			data["url_base"] = r.url_base
			if not self.qneg:
				data["label"] = r.label
			else:
				if r.label == Analyzer.target[1]:
					data["label"] = Analyzer.target_neg[1]
				elif r.label == Analyzer.target[2]:
					data["label"] = Analyzer.target_neg[2]
				else:
					data["label"] = r.label
			data["text"] = r.content[:900] + "... (see more at source)"
			data["id"] = r.ahash
			data["site_score"] = r.url_score
			data["date"] = str(r.date)
			data["feature"] = str(r.get_humanize_feature())
			data["counts"] = str(r.get_category_count())
			data["reason"] = r.reason
			lor.append(data)

		result = {}
		result["is_neg"] = self.qneg
		result["query"] = self.query
		result["hash"] = s.query_hash
		if not self.qneg:
			result["conclusion"] = Analyzer.target[self.ridx]
			result["scores"] = self.conclusion
		else:
			result["conclusion"] = Analyzer.target_neg[self.ridx]
			neg_concl = [self.conclusion[0], self.conclusion[2], self.conclusion[1], self.conclusion[3]]
			result["scores"] = neg_concl
		result["references"] = lor
		result["status"] = "Success"
		result["id"] = query_uuid

		self.db.insert_result_log(s.qid, self.conclusion[2], self.conclusion[1], self.conclusion[3], self.conclusion[0], result["conclusion"])
		return result

class Feedback:
	def __init__(self, client=None):
		self.client = client
		if not type(self.client) is dict:
			self.client = {}
		self.db = Database()
	
	def result(self, is_know, label, reason, quuid):
		result = {}
		try:
			if self.db.is_query_exist(quuid):
				self.db.insert_result_feedback(quuid, is_know, reason, label, self.client["ip"], self.client["browser"])
				result["status"] = "Success"
				result["message"] = "Result feedback noted"
			else:
				result["status"] = "Failed"
				result["message"] = "Invalid quuid"				
		except Exception as e:
			result["status"] = "Failed"
			result["message"] = "Database error"
			result["detail"] = str(e)
		return result

	def reference(self, is_related, label, reason, auuid):
		result = {}
		try:
			if self.db.is_reference_exist(auuid):
				self.db.insert_reference_feedback(auuid, is_related, reason, label, self.client["ip"], self.client["browser"])
				result["status"] = "Success"
				result["message"] = "Reference feedback noted"
			else:
				result["status"] = "Failed"
				result["message"] = "Invalid auuid"		
		except Exception as e:
			result["status"] = "Failed"
			result["message"] = "Database error"
			result["detail"] = str(e)
		return result

class Management:
	def __init__(self, client=None):
		self.client = client
		if not type(self.client) is dict:
			self.client = {}
		self.db = Database()
	
	def get_references(self, qhash):
		result = {}
		try:
			result["status"] = "Success"
			result["data"] = self.db.get_reference_by_qhash(qhash)
		except Exception as e:
			result["status"] = "Failed"
			result["message"] = "Database error"
			result["detail"] = str(e)
		return result

	def get_query_log(self):
		result = {}
		try:
			result["status"] = "Success"
			result["data"] = self.db.get_query_log()
		except Exception as e:
			result["status"] = "Failed"
			result["message"] = "Database error"
			result["detail"] = str(e)
		return result
