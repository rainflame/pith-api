import math
import nltk
from nltk import pos_tag
from nltk.stem import PorterStemmer
from operator import itemgetter
import pandas as pd
from threading import Lock

from models.post import Post
from models.block import Block

import database
import utils


nltk.download('averaged_perceptron_tagger')
ps = PorterStemmer()


# very rudimentary and misses things like pronouns and adverbs
def assign_pos_weight(cat):
    if "JJ" in cat: # adjective
        return 1
    elif "NN" in cat: # noun
        return 1
    elif "VB" in cat: # verb
        return 1
    else:
        return 0


def make_metric(key_word_list):
    stemmed = [ps.stem(w) for w in key_word_list]
    pos = pos_tag(key_word_list)
    weights = {w:assign_pos_weight(c) for w,c in pos}

    def metric(fd):
        score = 0
        word_freq = {w:fd[w] for w in key_word_list if w in fd}
        word_score = [weights[w] * math.log(f + 1) for w,f in word_freq.items()]
        return sum(word_score)

    return metric


def get_freqs(key_word_list, post_ids, block_ids):
    posts_obj = {p:Post(**database.get_post(p)) for p in post_ids}
    blocks_obj = {b:Block(**database.get_block(b)) for b in block_ids}

    blocks = []
    posts = []
    for k in key_word_list:
        blocks += [(b,k,blocks_obj[b].freq_dict[k]) for b in block_ids] 
        posts += [(p,k,posts_obj[p].freq_dict[k]) for p in post_ids] 

    return blocks, posts


def basic_search(key_word_list, blocks, posts): 
    key_word_list = list(set(key_word_list))

    metric = make_metric(key_word_list)

    blocks_freq = {}
    for b,k,f in blocks:
        if b not in blocks_freq: blocks_freq[b] = {}
        blocks_freq[b][k] = f

    posts_freq = {}
    for p,k,f in posts:
        if p not in posts_freq: posts_freq[p] = {}
        posts_freq[p][k] = f

    blocks_order = []
    for b,F in blocks_freq.items():
        blocks_order.append((b, metric(F)))
    blocks_order.sort(key=itemgetter(1), reverse=True)

    posts_order = []
    for p,F in posts_freq.items():
        posts_order.append((p, metric(F)))
    posts_order.sort(key=itemgetter(1), reverse=True)

    return blocks_order, posts_order


def all_scope_search(query):
    key_word_list = utils.text_tokens(query)

    blocks = []
    posts = []
    for k in key_word_list:
        blocks += [(b,k,f["freq"]) \
            for b,f in database.get_keyword_blocks(k).items()] 
        posts += [(p,k,f["freq"]) \
            for p,f in database.get_keyword_posts(k).items()] 

    return basic_search(key_word_list, blocks, posts)


def discussion_scope_search(query, discussion_id):
    key_word_list = utils.text_tokens(query)

    post_ids = database.get_discussion_posts(discussion_id)
    block_ids = database.get_discussion_blocks(discussion_id)
    blocks, posts = get_freqs(key_word_list, post_ids, block_ids) 

    return basic_search(key_word_list, blocks, posts)


def user_saved_scope_search(query, user_id):
    key_word_list = utils.text_tokens(query)

    post_ids = database.get_user_saved_posts(user_id)
    block_ids = database.get_user_saved_blocks(user_id)
    blocks, posts = get_freqs(key_word_list, post_ids, block_ids) 

    return basic_search(key_word_list, blocks, posts)
