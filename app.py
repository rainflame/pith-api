from json import dumps
from socketio import Namespace
from uuid import UUID

from models.global_manager import GlobalManager
from utils.utils import UUIDEncoder

gm = GlobalManager()
sio = gm.sio
app = gm.app


# TODO environ? authenticate_user import?
@sio.on('connect')
def connect(sid, environ):
  user_id = authenticate_user(environ)
  sio.save_session(sid, {'user_id': user_id})


# TODO leave active discussion
@sio.on('disconnect')
def disconnect(sid):
  #discussion_id = sio.session(sid)["active_discussion_id"]
  #user_id = sio.session(sid)["user_id"]
  self.gm.discussion_manager.leave(discussion_id, user_id)


"""
User-based functions.
"""


"""
Input: user_id<str>
Output: None
"""
# TODO clarify how this interacts with connect
@sio.on('create_user')
async def create_user(sid, json):
    #user_id = sio.session(sid)["user_id"]
    ip = json["user_id"]
    gm.user_manager.create(ip)


"""
Discussion-based functions.
"""
class DiscussionNamespace(Namespace):
  """
  Input: None
  Output: discussion_ids: [discussion_id1<str>, discussion_id2<str>, ...]
  """
  # TODO fix mongo db for new schema
  async def get(sid):
      discussion_ids = gm.discussion_manager.get_all()
      return dumps(discussion_ids, cls=UUIDEncoder)

  """
  Input: discussion_id<str>
  Output: posts_info : [
      {
          "post_id" : post_id<str>,
          "author" : user_id<str>,
          "author_name" : name<str>,
          "created_at" : created_at<str>,
          "blocks" : [block_id1<str>, block_id2<str>, ...] 
      }, 
  ...] 
  """
  async def get_posts(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      posts_info = gm.discussion_manager.get_posts_flattened(discussion_id)
      return dumps(posts_info, cls=UUIDEncoder)

  """
  Input: {
      "title" : title<str>,
      "theme" : theme<str>,
      "time_limit" : time_limit_in_secs<int>
  } 
  Output: discussion_id<str>
  """
  async def create(sid, json):
      title = json["title"]
      theme = json["theme"]
      time_limit = json["time_limit"] if "time_limit" in json else None
      block_char_limit = json["block_char_limit"] if "block_char_limit" in json else None
      summary_char_limit = json["summary_char_limit"] if "summary_char_limit" in json else None
      discussion_id = await gm.discussion_manager.create(
          title,
          theme,
          time_limit,
          block_char_limit,
          summary_char_limit,
      )
      serialized = dumps(discussion_id, cls=UUIDEncoder)
      # eventually might only want to do this on the global map, and even then...
      await sio.emit("created", serialized)
      return serialized

  """
  Input: discussion_id<str>
  Output: None
  """
  async def remove(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      gm.discussion_manager.remove(discussion_id)

  """
  Input: discussion_id<str>, user_id<str>, name<str>
  Output: {
      "discussion_id" : discussion_id<str>,
      "title" : title<str>,
      "theme" : theme<str>,
      "num_users" : num_users<int>
  } 
  """
  async def join(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      user_id = json["user_id"]
      name = json["name"]
      info = gm.discussion_manager.join(discussion_id, user_id, name)
      if info is not None:
          serialized = dumps(info, cls=UUIDEncoder)
          sio.enter_room(sid, discussion_id)
          await sio.emit("joined", serialized, room=discussion_id)
          return serialized
      return None

  """
  Input: discussion_id<str>, user_id<str>
  Output: {
      "discussion_id" : discussion_id<str>,
      "num_users" : num_users<int>
  } 
  """
  async def leave(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      user_id = json["user_id"]
      info = gm.discussion_manager.leave(discussion_id, user_id)
      serialized = dumps(info, cls=UUIDEncoder)
      sio.leave_room(sid, discussion_id)
      await sio.emit("left", serialized, room=discussion_id)
      return serialized

  """
  Input: discussion_id<str>, user_id<str>, blocks: [block_msg1<str>, block_msg2<str>, ...]
  Output: {"num_users" : num_users<int>} 
  """
  async def get_num_users(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      num_users = gm.discussion_manager.get_num_users(discussion_id)
      serialized = dumps({"num_users": num_users}, cls=UUIDEncoder)
      return serialized

  """
  Input: discussion_id<str>, user_id<str>, blocks: [block_msg1<str>, block_msg2<str>, ...]
  Output: post_info: {
      "post_id" : post_id<str>,
      "blocks" : [block_id1<str>, block_id2<str>, ...]
  } 
  """
  async def create_post(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      user_id = json["user_id"]
      blocks = json["blocks"]
      post_info = gm.discussion_manager.create_post(discussion_id, user_id, blocks)
      serialized = dumps(post_info, cls=UUIDEncoder)
      await sio.emit("created_post", serialized, room=discussion_id)
      return serialized

  """
  Input: discussion_id<str>, block_id<str>
  Output: block_info: {
      "block_id" : block_id<str>,
      "body" : body<str>,
      "tags" : [{
          tag<str> : {"owner" : user_id<str>}
      }, ...]
  }
  """
  async def get_block(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      block_id = json["block_id"]
      block_data = gm.discussion_manager.get_block_flattened(discussion_id, block_id)
      return dumps(block_data, cls=UUIDEncoder)

  """
  Input: user_id<str>, discussion_id<str>, block_id<str>
  Output: {"block_id" : block_id<str>}
  """
  async def save_block(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      user_id = json["user_id"]
      discussion_id = json["discussion_id"]
      block_id = json["block_id"]
      gm.user_manager.save_block(user_id, discussion_id, block_id)
      serialized = dumps({"block_id": block_id}, cls=UUIDEncoder)
      await sio.emit("saved_block", serialized, to=sid)
      return serialized

  """
  Input: user_id<str>, discussion_id<str>, block_id<str>
  Output: {"block_id" : block_id<str>}
  """
  async def unsave_block(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      user_id = json["user_id"]
      discussion_id = json["discussion_id"]
      block_id = json["block_id"]
      gm.user_manager.unsave_block(user_id, discussion_id, block_id)
      serialized = dumps({"block_id": block_id}, cls=UUIDEncoder)
      await sio.emit("unsaved_block", serialized, to=sid)
      return serialized

  """
  Input: user_id<str>, discussion_id<str>
  Output: block_ids: [block_id1<str>, block_id2<str>, ...]
  """
  async def get_saved_blocks(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      user_id = json["user_id"]
      discussion_id = json["discussion_id"]
      block_ids = gm.user_manager.get_user_saved_block_ids(user_id, discussion_id)
      return dumps(block_ids, cls=UUIDEncoder)

  """
  Input: discussion_id<str>, user_id<str>, block_id<str>, tag<str> 
  Output: {
      "block_id" : block_id<str>,
      "user_id" : user_id<str>,
      "tag" : tag<str>
  }
  """
  async def block_add_tag(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      user_id = json["user_id"]
      block_id = json["block_id"]
      tag = json["tag"]
      gm.discussion_manager.block_add_tag(discussion_id, user_id, block_id, tag)
      serialized = dumps({"block_id": block_id, "user_id": user_id, "tag": tag},
                         cls=UUIDEncoder)
      await sio.emit("tagged_block", serialized, room=discussion_id)
      return serialized

  """
  Input: discussion_id<str>, user_id<str>, block_id<str>, tag<str> 
  Output: {
      "block_id" : block_id<str>,
      "tag" : tag<str>
  }
  """
  async def block_remove_tag(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      user_id = json["user_id"]
      block_id = json["block_id"]
      tag = json["tag"]
      gm.discussion_manager.block_remove_tag(discussion_id, user_id, block_id, tag)
      serialized = dumps({"block_id": block_id, "tag": tag},
                         cls=UUIDEncoder)
      await sio.emit("untagged_block", serialized, room=discussion_id)
      return serialized

  """
  Input: discussion_id<str>, query<str> 
  Output: result: {
      "posts" : [post_id1<str>, post_id2<str>, ...], 
      "blocks" : [block_id1<str>, block_id2<str>, ...] 
  } 
  """
  async def search_basic(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      query = json["query"]
      result = gm.discussion_manager.discussion_scope_search(discussion_id, query)
      serialized = dumps(result, cls=UUIDEncoder)
      return serialized

  """
  Input: discussion_id<str>, tags: [tag1<str>, tag2<str>, ...] 
  Output: result: {
      "posts" : [post_id1<str>, post_id2<str>, ...], 
      "blocks" : [block_id1<str>, block_id2<str>, ...] 
  } 
  """
  async def search_tags(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      tags = json["tags"]
      result = gm.discussion_manager.discussion_tag_search(discussion_id, tags)
      serialized = dumps(result, cls=UUIDEncoder)
      return serialized

  """
  Input: discussion_id<str>, user_id<str>, query<str> 
  Output: result: {
      "posts" : [post_id1<str>, post_id2<str>, ...], 
      "blocks" : [block_id1<str>, block_id2<str>, ...] 
  } 
  """
  async def search_user_saved_basic(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      user_id = json["user_id"]
      query = json["query"]
      result = gm.discussion_manager.user_saved_scope_search(discussion_id, user_id, query)
      serialized = dumps(result, cls=UUIDEncoder)
      return serialized

  """
  Input: discussion_id<str>, user_id<str>, tags: [tag1<str>, tag2<str>, ...] 
  Output: result: {
      "posts" : [post_id1<str>, post_id2<str>, ...], 
      "blocks" : [block_id1<str>, block_id2<str>, ...] 
  } 
  """
  async def search_user_saved_tags(sid, json):
      #user_id = sio.session(sid)["user_id"]
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      user_id = json["user_id"]
      tags = json["tags"]
      result = gm.discussion_manager.user_saved_tag_search(discussion_id, user_id, tags)
      serialized = dumps(result, cls=UUIDEncoder)
      return serialized

  """
  Input: discussion_id<str>, body<str> 
  Output: On success: {
    "block_id": block_id<str>,
    "body": body<str>
  } 
  On failure: {
    "err": err<int>
  }
  """
  async def summary_add_block(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      body = json["body"]
      block_id, err = gm.discussion_manager.summary_add_block(discussion_id, body)
      if err is None:
          serialized = {"block_id": block_id, "body": body}
          await sio.emit("added_summary_block", serialized, room=discussion_id)
          return serialized
      else:
          serialized = {"err": err}
          return serialized

  """
  Input: discussion_id<str>, block_id<str>, body<str>
  Output: On success: {
    "block_id": block_id<str>,
    "body": body<str>
  } 
  On failure: {
    "err": err<int>
  }
  """
  async def summary_modify_block(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      block_id = json["block_id"]
      body = json["body"]
      err = gm.discussion_manager.summary_modify_block(discussion_id, block_id, body)
      if err is None:
          serialized = {"block_id": block_id, "body": body}
          await sio.emit("modified_summary_block", serialized, room=discussion_id)
          return serialized
      else:
          serialized = {"err": err}
          return serialized

  """
  Input: discussion_id<str>, block_id<str>
  Output: {
    "block_id": block_id<str>,
  } 
  """
  async def summary_remove_block(sid, json):
      #discussion_id = sio.session(sid)["active_discussion_id"]
      discussion_id = json["discussion_id"]
      block_id = json["block_id"]
      gm.discussion_manager.summary_remove_block(discussion_id, block_id)
      serialized = {"block_id": block_id}
      await sio.emit("removed_summary_block", serialized, room=discussion_id)
      return serialized

sio.register_namespace(DiscussionNamespace('/discussion'))
