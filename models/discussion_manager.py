import asyncio
from arq import create_pool
from arq.connections import RedisSettings
from threading import Thread
from utils import utils

from models.block import Block
from models.discussion import Discussion
from models.post import Post
from models.tag import Tag

from search.basic_search import basic_search
from search.tag_search import tag_search

class DiscussionManager:

    def __init__(self, gm, sio, db):
        self.sio = sio
        self.discussions = db["discussions"]
        self.gm = gm
        self.expire_loop = asyncio.new_event_loop()
        t = Thread(target=self.start_loop, args=(self.expire_loop,))
        t.start()

    def start_loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    """
    Of discussions.
    """

    def _insert(self, discussion_obj):
        discussion_data = discussion_obj.__dict__
        self.discussions.insert_one(discussion_data)

    def remove(self, discussion_id):
        self.discussions.remove({
            "_id": discussion_id
        })

    def get(self, discussion_id):
        discussion_data = self.discussions.find_one({
            "_id": discussion_id
        })
        return discussion_data

    def get_all(self):
        discussion_cursor = self.discussions.find()
        discussion_list = []
        for u in discussion_cursor:
            discussion_list.append(u["_id"])
        return discussion_list

    async def expire(self, discussion_id):
        self.discussions.update_one(
            {"_id": discussion_id},
            {"$set": {"expired": True}}
        )
        discussion_data = self.get(discussion_id)
        serialized = dumps({"discussion_id" : discussion_id}, cls=utils.UUIDEncoder)
        await self.sio.emit("discussion_expired", serialized)

    async def _wait_to_expire(self, discussion_id, time_limit):
        await asyncio.sleep(time_limit)
        await self.expire(discussion_id)

    def create(self, title=None, theme=None, time_limit=None):
        discussion_obj = Discussion(title, theme, time_limit)
        discussion_id = discussion_obj._id
        self._insert(discussion_obj)
        if time_limit is not None:
            asyncio.run_coroutine_threadsafe(
                self._wait_to_expire(discussion_id, time_limit),
                self.expire_loop,
            )
        return discussion_id

    """
    Within a discussion.
    First arg is always `discussion_id`.
    """

    def _is_user(self, discussion_id, user_id):
        discussion_data = self.get(discussion_id)
        return user_id in discussion_data["users"]

    def _name_exists(self, discussion_id, name):
        discussion_data = self.get(discussion_id)
        return name in list(
            [u["name"] for u in discussion_data["users"].values()]
        )

    def join(self, discussion_id, user_id, name):
        if not self._is_user(discussion_id, user_id):
            if not self._name_exists(discussion_id, name):
                self.gm.user_manager.join_discussion(user_id, discussion_id, name)
                self.discussions.update_one(
                    {"_id": discussion_id},
                    {"$set": {"users.{}".format(user_id): {"name": name}}}
                )
        discussion_data = self.get(discussion_id)
        return {
            "discussion_id": discussion_id,
            "title": discussion_data["title"],
            "theme": discussion_data["theme"],
        }

    def leave(self, discussion_id, user_id):
        self.gm.user_manager.leave_discussion(user_id, discussion_id)
        if self._is_user(discussion_id, user_id):
            self.discussions.update_one(
                {"_id": discussion_id},
                {"$unset": {"users.{}".format(user_id): 0}}
            )

    def get_users(self, discussion_id):
        discussion_data = self.get(discussion_id)
        user_ids = list(discussion_data["users"].keys())
        return user_ids

    def get_num_users(self, discussion_id):
        discussion_data = self.get(discussion_id)
        user_ids = list(discussion_data["users"].keys())
        num_users = len(user_ids)
        return num_users

    def get_names(self, discussion_id):
        discussion_data = self.get(discussion_id)
        names = list([u["name"] for u in discussion_data["users"].values()])
        return names

    def get_user_name(self, discussion_id, user_id):
        discussion_data = self.get(discussion_id)
        name = discussion_data["users"][user_id]["name"]
        return name

    def create_post(self, discussion_id, user_id, blocks):
        post_obj = Post(user_id)
        post_id = post_obj._id

        block_ids = []
        freq_dicts = []
        for b in blocks:
            block_obj = Block(user_id, post_id, b)
            freq_dicts.append(block_obj.freq_dict)
            block_id = block_obj._id
            block_ids.append(block_id)
            block_data = block_obj.__dict__
            self.discussions.update_one(
                {"_id": discussion_id},
                {"$set": {"history_blocks.{}".format(block_id): block_data}}
            )

        post_obj.blocks = block_ids
        post_obj.freq_dict = utils.sum_dicts(freq_dicts)
        post_data = post_obj.__dict__
        self.discussions.update_one(
            {"_id": discussion_id},
            {"$set": {"history.{}".format(post_id): post_data}}
        )
        self.gm.user_manager.insert_post_user_history(user_id, discussion_id, post_id)

        post_info = {
            "post_id": post_data["_id"],
            "blocks": post_data["blocks"],
        }

        post_data["author_name"] = self.get_user_name(discussion_id, user_id)

        return post_data

    def get_post(self, discussion_id, post_id):
        discussion_data = self.get(discussion_id)
        post_data = discussion_data["history"][post_id]
        return post_data

    def _get_post_ids(self, discussion_id):
        discussion_data = self.get(discussion_id)
        return list(discussion_data["history"].keys())

    def _get_block_ids(self, discussion_id):
        discussion_data = self.get(discussion_id)
        return list(discussion_data["history_blocks"].keys())

    def get_posts(self, discussion_id):
        discussion_data = self.get(discussion_id)
        history = discussion_data["history"]
        return list(history.values())  # give data

    def get_posts_flattened(self, discussion_id):
        posts = self.get_posts(discussion_id)
        posts_info = [{
            "post_id": p["_id"],
            "author": p["user"],
            "author_name": self.get_user_name(discussion_id, p["user"]),
            "created_at": p["created_at"],
            "blocks": p["blocks"],
        } for p in posts]
        return posts_info

    def get_block(self, discussion_id, block_id):
        discussion_data = self.get(discussion_id)
        block_data = discussion_data["history_blocks"][block_id]
        return block_data

    def get_block_flattened(self, discussion_id, block_id):
        block_data = self.get_block(discussion_id, block_id)
        block_info = {
            "block_id": block_data["_id"],
            "body": block_data["body"],
            "tags": block_data["tags"],
        }
        return block_info

    def get_blocks(self, discussion_id):
        discussion_data = self.get(discussion_id)
        history_blocks = discussion_data["history_blocks"]
        return list(history_blocks.values())  # give data

    def _is_tag(self, discussion_id, tag):
        discussion_data = self.get(discussion_id)
        return tag in discussion_data["internal_tags"]

    def _get_tag(self, discussion_id, tag):
        assert(self._is_tag(discussion_id, tag))
        discussion_data = self.get(discussion_id)
        tag_data = discussion_data["internal_tags"][tag]
        return tag_data

    def _is_tag_owner_post(self, discussion_id, user_id, post_id, tag):
        assert(self._is_tag(discussion_id, tag))
        post_data = self.get_post(discussion_id, post_id)
        assert(tag in post_data["tags"])
        return post_data["tags"][tag]["owner"]

    def _is_tag_owner_block(self, discussion_id, user_id, block_id, tag):
        assert(self._is_tag(discussion_id, tag))
        block_data = self.get_block(discussion_id, block_id)
        assert(tag in block_data["tags"])
        return block_data["tags"][tag]["owner"]

    def _create_tag(self, discussion_id, tag):
        if not self._is_tag(discussion_id, tag):
            tag_obj = Tag(tag)
            tag_data = tag_obj.__dict__
            self.discussions.update_one(
                {"_id": discussion_id},
                {"$set": {"internal_tags.{}".format(tag): tag_data}}
            )
        else:
            tag_data = self._get_tag(discussion_id, tag)
        return tag_data

    def _is_tag_post(self, discussion_id, post_id, tag):
        """
        Only use this once the tag has been created for the discussion.
        """
        assert(self._is_tag(discussion_id, tag))
        post_data = self.get_post(discussion_id, post_id)
        return tag in post_data["tags"]

    def post_add_tag(self, discussion_id, user_id, post_id, tag):
        self._create_tag(discussion_id, tag)
        if not self._is_tag_post(discussion_id, post_id, tag):
            self.discussions.update_one(
                {"_id": discussion_id},
                {"$set": {
                    "history.{}.tags.{}".format(
                        post_id, tag): {"owner": user_id}
                    }
                }
            )

    def post_remove_tag(self, discussion_id, user_id, post_id, tag):
        if self._is_tag_post(discussion_id, post_id, tag):
            if self._is_tag_owner_post(discussion_id, user_id, post_id, tag):
                self.discussions.update_one(
                    {"_id": discussion_id},
                    {"$unset": {
                        "history.{}.tags.{}".format(
                            post_id, tag): 0
                        }
                    }
                )

    def _is_tag_block(self, discussion_id, block_id, tag):
        """
        Only use this once the tag has been created for the discussion.
        """
        assert(self._is_tag(discussion_id, tag))
        block_data = self.get_block(discussion_id, block_id)
        return tag in block_data["tags"]

    def block_add_tag(self, discussion_id, user_id, block_id, tag):
        self._create_tag(discussion_id, tag)
        if not self._is_tag_block(discussion_id, block_id, tag):
            self.discussions.update_one(
                {"_id": discussion_id},
                {"$set": {
                    "history_blocks.{}.tags.{}".format(
                        block_id, tag): {"owner": user_id}
                    }
                }
            )

    def block_remove_tag(self, discussion_id, user_id, block_id, tag):
        if self._is_tag_block(discussion_id, block_id, tag):
            if self._is_tag_owner_block(discussion_id, user_id, block_id, tag):
                self.discussions.update_one(
                    {"_id": discussion_id},
                    {"$unset": {
                        "history_blocks.{}.tags.{}".format(
                            block_id, tag): 0
                        }
                    }
                )

    def discussion_scope_search(self, discussion_id, query):
        posts_data = self.get_posts(discussion_id)
        blocks_data = self.get_blocks(discussion_id) 
        return basic_search(query, blocks_data, posts_data)

    def discussion_tag_search(self, discussion_id, tags):
        posts_data = self.get_posts(discussion_id)
        blocks_data = self.get_blocks(discussion_id) 
        return tag_search(tags, blocks_data, posts_data)

    def get_user_saved_posts(self, discussion_id, user_id):
        post_ids = self.gm.user_manager.get_user_saved_post_ids(user_id, discussion_id)
        posts = [self.get_post(discussion_id, p) for p in post_ids]
        return posts

    def get_user_saved_blocks(self, discussion_id, user_id):
        block_ids = self.gm.user_manager.get_user_saved_block_ids(user_id, discussion_id)
        blocks = [self.get_block(discussion_id, b) for b in block_ids]
        return blocks

    def user_saved_scope_search(self, discussion_id, user_id, query):
        posts_data = self.get_user_saved_posts(discussion_id, user_id)
        blocks_data = self.get_user_saved_blocks(discussion_id, user_id)
        return basic_search(query, blocks_data, posts_data)

    def user_saved_tag_search(self, discussion_id, user_id, tags):
        posts_data = self.get_user_saved_posts(discussion_id, user_id)
        blocks_data = self.get_user_saved_blocks(discussion_id, user_id)
        return tag_search(tags, blocks_data, posts_data)
