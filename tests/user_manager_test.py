import logging
import sys
import unittest
import uuid

from models.global_manager import GlobalManager
from models.user import User
from models.post import Post
from models.block import Block


class UserManagerTest(unittest.TestCase):

    def setUp(self):
        gm = GlobalManager()
        self.user_manager = gm.user_manager
        self.log = logging.getLogger("UserManagerTest")

    def test_create_get(self):
        ip = "12345"
        self.user_manager.create(ip)
        user_data = self.user_manager.get(ip)
        self.assertEqual(user_data["_id"], ip)
        users_data = self.user_manager.get_all()
        user_ips = [u["_id"] for u in users_data]
        self.assertTrue(ip in user_ips)

        # repeat creation and see if idempotent
        self.user_manager.create(ip)
        user_data = self.user_manager.get(ip)
        self.assertEqual(user_data["_id"], ip)
        users_data = self.user_manager.get_all()
        user_ips = [u["_id"] for u in users_data]
        self.assertTrue(ip in user_ips)

    def test_in_discussion(self):
        ip = "12345"
        discussion_id = "in_discussion" + str(uuid.uuid4().hex)
        name = "hello"
        self.user_manager.create(ip)

        # joining (only user-side)
        self.user_manager.join_discussion(ip, discussion_id, name)
        user_data = self.user_manager.get(ip)
        self.assertTrue(discussion_id in user_data["discussions"])
        self.assertTrue(user_data["discussions"][discussion_id]["active"])

        # posting (only user-side)
        post_obj1 = Post(ip)
        post_id1 = post_obj1._id
        self.user_manager.insert_post_user_history(ip, discussion_id, post_id1)
        user_data = self.user_manager.get(ip)
        self.assertTrue(
            user_data["discussions"][discussion_id]["history"] \
                == [post_id1]
        )        
        post_obj2 = Post(ip)
        post_id2 = post_obj2._id
        self.user_manager.insert_post_user_history(ip, discussion_id, post_id2)
        user_data = self.user_manager.get(ip)
        self.assertTrue(
            user_data["discussions"][discussion_id]["history"] \
                == [post_id1, post_id2]
        )        

        # leaving (only user-side)
        self.user_manager.leave_discussion(ip, discussion_id)
        user_data = self.user_manager.get(ip)
        # still keep discussion in those that we visited
        self.assertTrue(discussion_id in user_data["discussions"])
        self.assertFalse(user_data["discussions"][discussion_id]["active"])

    def test_saving_post(self):
        ip = "12345"
        ip2 = "67890"
        name = "hello"
        discussion_id = "saving_post" + str(uuid.uuid4().hex)
        self.user_manager.create(ip)
        self.user_manager.join_discussion(ip, discussion_id, name)

        post_obj = Post(ip2)
        post_id = post_obj._id
        self.user_manager.save_post(ip, discussion_id, post_id)
        post_ids = self.user_manager.get_user_saved_post_ids(ip, discussion_id)
        self.assertTrue(post_id in post_ids)
        self.user_manager.unsave_post(ip, discussion_id, post_id)
        post_ids = self.user_manager.get_user_saved_post_ids(ip, discussion_id)
        self.assertFalse(post_id in post_ids)

        self.user_manager.leave_discussion(ip, discussion_id)

    def test_saving_block(self):
        ip = "12345"
        ip2 = "67890"
        name = "hello"
        discussion_id = "saving_block" + str(uuid.uuid4().hex)
        self.user_manager.create(ip)
        self.user_manager.join_discussion(ip, discussion_id, name)

        post_obj = Post(ip2)
        block_obj = Block("test", ip2, post_obj._id)
        block_id = block_obj._id
        self.user_manager.save_block(ip, discussion_id, block_id)
        block_ids = self.user_manager.get_user_saved_block_ids(ip, discussion_id)
        self.assertTrue(block_id in block_ids)
        self.user_manager.unsave_block(ip, discussion_id, block_id)
        block_ids = self.user_manager.get_user_saved_block_ids(ip, discussion_id)
        self.assertFalse(block_id in block_ids)

        self.user_manager.leave_discussion(ip, discussion_id)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr)
    logging.getLogger("UserManagerTest").setLevel(logging.DEBUG)
    unittest.main()