import constants
import datetime
import error

from models.block import Block
from models.discussion import Discussion
from models.post import Post
from models.tag import Tag

from search.basic_search import basic_search
from search.tag_search import tag_search

from utils import utils


class DiscussionManager:

    def __init__(self, gm, sio, db):
        self.sio = sio
        self.discussions = db["discussions"]
        self.gm = gm

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

    # async def expire(self, discussion_id):
    #     self.
    #     discussion_data = self.get(discussion_id)
    #     serialized = dumps({"discussion_id": discussion_id}, cls=utils.UUIDEncoder)
    #     await self.sio.emit("discussion_expired", serialized)

    async def create(
        self,
        title=None,
        theme=None,
        time_limit=None,
        block_char_limit=None,
        summary_char_limit=None
    ):
        discussion_obj = Discussion(title, theme, time_limit, block_char_limit, summary_char_limit)
        discussion_id = discussion_obj._id
        self._insert(discussion_obj)

       # add the expire event
        if time_limit is not None:
            redis_queue = await constants.redis_pool()
            await redis_queue.enqueue_job("expire_discussion", discussion_id, _defer_by=datetime.timedelta(seconds=time_limit))

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
        is_user = self._is_user(discussion_id, user_id)

        if not is_user:
            if self._name_exists(discussion_id, name):
                return None
            self.gm.user_manager.join_discussion(user_id, discussion_id, name)
            self.discussions.update_one(
                {"_id": discussion_id},
                {"$set": {"users.{}".format(user_id): {"name": name, "active": True}}}
            )
            discussion_data = self.get(discussion_id)
            return {
                "discussion_id": discussion_id,
                "title": discussion_data["title"],
                "theme": discussion_data["theme"],
                "num_users": self.get_num_users(discussion_id),
            }
        else:
            if name != self.get_user_name(discussion_id, user_id):
                # in the case that the user enters a new name, just return the discussion
                # info without erroring. This indicates that the user cleared their
                # localstorage on the fontend without reloading the page. This should
                # very rarely happen.
                discussion_data = self.get(discussion_id)
                return {
                    "discussion_id": discussion_id,
                    "title": discussion_data["title"],
                    "theme": discussion_data["theme"],
                    "num_users": self.get_num_users(discussion_id),
                }
            self.gm.user_manager.join_discussion(user_id, discussion_id, name)
            self.discussions.update_one(
                {"_id": discussion_id},
                {"$set": {"users.{}.active".format(user_id): True}}
            )
            discussion_data = self.get(discussion_id)
            return {
                "discussion_id": discussion_id,
                "title": discussion_data["title"],
                "theme": discussion_data["theme"],
                "num_users": self.get_num_users(discussion_id),
            }

    def leave(self, discussion_id, user_id):
        self.gm.user_manager.leave_discussion(user_id, discussion_id)
        if self._is_user(discussion_id, user_id):
            self.discussions.update_one(
                {"_id": discussion_id},
                {"$set": {"users.{}.active".format(user_id): False}}
            )

        return {
            "discussion_id": discussion_id,
            "num_users": self.get_num_users(discussion_id),
        }

    def get_num_users(self, discussion_id):  # only active users
        discussion_data = self.get(discussion_id)
        num_users = sum([u["active"] for u in discussion_data["users"].values()])
        return num_users

    def get_users(self, discussion_id):
        discussion_data = self.get(discussion_id)
        user_ids = list(discussion_data["users"].keys())
        return user_ids

    def get_names(self, discussion_id):
        discussion_data = self.get(discussion_id)
        names = list([u["name"] for u in discussion_data["users"].values()])
        return names

    def get_users(self, discussion_id):
        discussion_data = self.get(discussion_id)
        user_ids = list([k for k, u in discussion_data["users"].items() if u["active"]])
        return user_ids

    def get_names(self, discussion_id):
        discussion_data = self.get(discussion_id)
        names = list([u["name"] for u in discussion_data["users"].values() if u["active"]])
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
            block_obj = Block(b, user_id, post_id)
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
            "created_at": post_data["created_at"],
        }
        post_info["author_name"] = self.get_user_name(discussion_id, user_id)

        return post_info

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
        try:
            block_data = discussion_data["history_blocks"][block_id]
        except:
            block_data = None
        return block_data

    def get_block_flattened(self, discussion_id, block_id):
        block_data = self.get_block(discussion_id, block_id)
        if block_data is not None:
            block_info = {
                "block_id": block_data["_id"],
                "body": block_data["body"],
                "tags": block_data["tags"],
            }
        else:
            block_info = None
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

    def _transclusion_get_body(self, text):
        match_res = constants.transclusion_header.match(text)
        if match_res:
            return text[len(match_res[0]):]
        else:
            return text

    def _transclusion_get_id(self, text):
        match_res = constants.transclusion_header.match(text)
        if match_res:
            return match_res[0][11:-1]  # get stuff between "transclude<" and ">"
        else:
            return None

    def _get_block_limit(self, discussion_id):
        discussion_data = self.get(discussion_id)
        return discussion_data["block_char_limit"]

    def _get_summary_char_left(self, discussion_id):
        discussion_data = self.get(discussion_id)
        return discussion_data["summary_char_left"]

    def _set_summary_char_left(self, discussion_id, new_limit):
        self.discussions.update_one(
            {"_id": discussion_id},
            {"$set": {"summary_char_left": new_limit}}
        )

    def get_summary_block(self, discussion_id, block_id):
        discussion_data = self.get(discussion_id)
        return discussion_data["summary_blocks"][block_id]

    def summary_add_block(self, discussion_id, body):
        raw_body = self._transclusion_get_body(body)
        body_len = len(raw_body)
        block_limit_len = self._get_block_limit(discussion_id)
        if block_limit_len:
            if body_len > block_limit_len:
                return None, error.D_S_B_C_BC

        summ_char_left = self._get_summary_char_left(discussion_id)
        if summ_char_left:
            if body_len > summ_char_left:
                return None, error.D_S_B_C_SC
            else:
                summ_char_left = summ_char_left - body_len
                self._set_summary_char_left(discussion_id, summ_char_left)

        block_obj = Block(body)
        block_id = block_obj._id
        self.discussions.update_one(
            {"_id": discussion_id},
            {"$set": {"summary_blocks.{}".format(block_id): block_obj.__dict__}}
        )
        return block_id, None

    def summary_modify_block(self, discussion_id, block_id, body):
        # should not be getting transclusions when modifying
        block_data = self.get_summary_block(discussion_id, block_id)
        original_body = block_data["body"]
        body_len = len(body)
        block_limit_len = self._get_block_limit(discussion_id)
        if block_limit_len:
            if body_len > block_limit_len:
                return error.D_S_B_C_BC

        summ_char_left = self._get_summary_char_left(discussion_id)
        if summ_char_left:
            new_left = summ_char_left + len(original_body) - body_len
            if new_left < 0:
                return error.D_S_B_C_SC
            else:
                self._set_summary_char_left(discussion_id, new_left)

        block_data["body"] = body
        self.discussions.update_one(
            {"_id": discussion_id},
            {"$set": {"summary_blocks.{}".format(block_id): block_data}}
        )
        return None

    def summary_remove_block(self, discussion_id, block_id):
        self.discussions.update_one(
            {"_id": discussion_id},
            {"$set": {"summary_blocks.{}".format(block_id): 0}}
        )
