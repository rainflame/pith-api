"""
Here, we put unit functions in the discussion namespace.
Many of the unit functions have no need of the discussion information.
"""

from datetime import datetime
import logging
from mongoengine import DoesNotExist

import constants
from error import Errors
from utils import utils

from models.discussion import (
  Cursor,
  TimeInterval,
  Discussion,
  Unit,
  User,
)


class DiscussionManager:

    def __init__(self, gm):
        self.gm = gm
        self.redis_queue = self.gm.redis_queue

    """
    Unprotected helper functions.
    """

    # pointer
    def _get(self, discussion_id):
        return Discussion.objects(id=discussion_id)

    # pointer
    def _get_unit(self, unit_id):
        return Unit.objects(id=unit_id)

    # access
    def _get_user(self, discussion_id, user_id):
        discussion = self._get(discussion_id)
        return discussion.get().users.filter(id=user_id)

    # pointer
    def _get_user_ref(self, discussion_id, user_id):
        discussion = self._get(discussion_id)
        return discussion.filter(users__id=user_id)

    def _get_ancestors(self, unit_id):
        ancestors = []
        curr = unit_id
        while curr != "": # root 
          ancestors.append(curr)
          unit = self._get_unit(curr).get()
          curr = unit.parent
        return ancestors

    def _get_tree(self, unit_id):
        tree = [unit_id]
        curr_depth = [unit_id]
        while len(curr_depth) > 0:
          next_depth = []
          for c in curr_depth:
            unit = self._get_unit(c).get()
            next_depth += unit.children
          tree += next_depth
          curr_depth = next_depth
        return tree

    def _time_entry(self, discussion_id, user_id):
        """
        NOTE: Requires viewed_unit to be properly set.
        """
        user = self._get_user(discussion_id, user_id)
        now = datetime.utcnow()
        time_interval = TimeInterval(
          unit_id=user.get().viewed_unit,
          start_time=user.get().start_time,
          end_time=now) 

        user_ref = self._get_user_ref(discussion_id, user_id)
        #### MONGO
        user_ref.update(
          push__users__S__timeline=time_interval,
          set__users__S__start_time=now # update start time for new unit
        )
        #### MONGO

        user = self._get_user(discussion_id, user_id)
        return user.get().timeline[-1] #time_interval

    def _acquire_edit(self, discussion_id, user_id, unit_id):
        unit = self._get_unit(unit_id)
        user_ref = self._get_user_ref(discussion_id, user_id)
        #### MONGO
        unit.update(edit_privilege=user_id)
        user_ref.update(push__users__S__editing=unit_id)
        #### MONGO

    def _acquire_position(self, discussion_id, user_id, unit_id):
        unit = self._get_unit(unit_id)
        user_ref = self._get_user_ref(discussion_id, user_id)
        #### MONGO
        unit.update(position_privilege=user_id)
        user_ref.update(push__users__S__moving=unit_id)
        #### MONGO

    def _release_edit(self, discussion_id, user_id, unit_id):
        unit = self._get_unit(unit_id)
        user_ref = self._get_user_ref(discussion_id, user_id)
        #### MONGO
        unit.update(edit_privilege=None)
        user_ref.update(pull__users__S__editing=unit_id)
        #### MONGO

    def _release_position(self, discussion_id, user_id, unit_id):
        unit = self._get_unit(unit_id)
        user_ref = self._get_user_ref(discussion_id, user_id)
        #### MONGO
        unit.update(position_privilege=None)
        user_ref.update(pull__users__S__moving=unit_id)
        #### MONGO

    def _retrieve_links(self, pith):
      links = constants.LINK_PATTERN.findall(pith)
      links = [l for l in links if l != ""] # non-empty
      return links

    def _contains_chat_link(self, links):
      for unit_id in links:
          unit = self._get_unit(unit_id).get()
          if unit.in_chat:
            return True
      return False

    def _remove_chat_links(self, pith):
      links = self._retrieve_links(pith)
      chat_links = [unit_id for unit_id in links \
        if self._get_unit(unit_id).get().in_chat]
      formatted = set([constants.LINK_WRAPPER.format(c) for c in chat_links])
      for f in formatted:
        pith = pith.replace(f, constants.DEAD_LINK)
      return pith

    def _get_position(self, parent, unit_id):
      children = self._get_unit(parent).get().children
      if unit_id in children:
        return children.index(unit_id)
      else:
        return -1

    def _chat_meta(self, discussion_id, unit_id):
      unit = self._get_unit(unit_id).get()
      user = self._get_user(discussion_id, unit.author)
      response = {
        "unit_id": unit_id,
        "pith": unit.pith,
        "author": user.get().name,
        "created_at": unit.created_at.strftime(constants.DATE_TIME_FMT)
      }
      return response

    def _doc_meta(self, discussion_id, unit_id):
      unit = self._get_unit(unit_id).get()
      response = {
        "unit_id": unit_id,
        "pith": unit.pith,
        "hidden": unit.hidden,
        "created_at": unit.created_at.strftime(constants.DATE_TIME_FMT),
        "edit_privilege": unit.edit_privilege,
        "position_privilege": unit.position_privilege,
        "children": list(unit.children),
        "backlinks": list(unit.backward_links),
      }
      return response

    def _chat_metas(self, discussion_id, chat_meta_ids):
        chat_meta = [self._chat_meta(discussion_id, id) for id in list(set(chat_meta_ids))]
        return chat_meta

    def _doc_metas(self, discussion_id, doc_meta_ids):
        doc_meta = [self._doc_meta(discussion_id, id) for id in list(set(doc_meta_ids))]
        return doc_meta

    """
    Verification functions. Require specific arguments in most cases.
    args should only contain self. Other arguments should be in kwargs so they are queryable.
    """

    def _check_discussion_id(func):
      """
      Check discussion_id is valid.
      """
      def helper(self, **kwargs):
        discussion_id = kwargs["discussion_id"]
        try:
          self._get(discussion_id).get()
          #Discussion.objects.get(id=discussion_id)
          return func(self, **kwargs)
        except DoesNotExist:
          return Errors.BAD_DISCUSSION_ID
      return helper
          
    def _check_user_id(func):
      """
      Check user_id is valid.
      NOTE: Requires _check_discussion_id.
      """
      def helper(self, **kwargs):
        discussion_id = kwargs["discussion_id"]
        user_id = kwargs["user_id"]
        user_ref = self._get_user_ref(discussion_id, user_id)
        if len(user_ref) == 0:
          return Errors.BAD_USER_ID
        else:
          return func(self, **kwargs)
      return helper

    def _check_unit_id(func):
      """
      Check unit_id is valid.
      """
      def helper(self, **kwargs):
        unit_id = kwargs["unit_id"]
        try:
          Unit.objects.get(id=unit_id)
          return func(self, **kwargs)
        except DoesNotExist:
          return Errors.BAD_UNIT_ID
      return helper 

    def _check_units(func):
      """
      Check units are valid.
      """
      def helper(self, **kwargs):
        units = kwargs["units"]
        try:
          for unit_id in units:
            Unit.objects.get(id=unit_id)
          return func(self, **kwargs)
        except DoesNotExist:
          return  Errors.BAD_UNIT_ID
      return helper 

    def _verify_position(func):
      """
      Check position is valid for unit.
      NOTE: Requires _check_unit_id.
      """
      def helper(self, **kwargs):
        unit_id = kwargs["unit_id"]
        position = kwargs["position"]
        unit = self._get_unit(unit_id).get()
        if position > len(unit.children) or position < -1:
          return Errors.BAD_POSITION
        else: 
          return func(self, **kwargs)
      return helper

    def _verify_edit_privilege(func):
      """
      Check user can edit unit.
      NOTE: Requires _check_user_id and _check_unit_id.
      """
      def helper(self, **kwargs):
        unit_id = kwargs["unit_id"]
        user_id = kwargs["user_id"]
        unit = self._get_unit(unit_id).get()
        if unit.edit_privilege != user_id:
          return Errors.BAD_EDIT_TRY
        else:
          return func(self, **kwargs)
      return helper

    def _verify_positions_privilege(func):
      """
      Check user can change position of unit.
      NOTE: Requires _check_user_id and _check_unit_id.
      """
      def helper(self, **kwargs):
        units = kwargs["units"]
        user_id = kwargs["user_id"]
        for unit_id in units:
          unit = self._get_unit(unit_id).get()
          if unit.position_privilege != user_id:
            return Errors.BAD_POSITION_TRY
        return func(self, **kwargs)
      return helper

    def _verify_parent(func):
      """
      Check parent and position are valid.
      If any of the units are the potential parent or ancestors of the parent, the parent is invalid.
      NOTE: Requires _check_units on units. 
      """
      def helper(self, **kwargs):
        units = kwargs["units"]
        parent = kwargs["parent"]
        position = kwargs["position"]

        try:
          Unit.objects.get(id=parent)
        except DoesNotExist:
          return Errors.BAD_UNIT_ID

        parent_ptr = self._get_unit(parent)
        if position > len(parent_ptr.get().children) or position < 0: # fixed
          return Errors.BAD_POSITION 

        ancestors = self._get_ancestors(parent)
        inter = set(ancestors).intersection(set(units))
        if len(inter) > 0:
          return Errors.BAD_PARENT 
        else:
          return func(self, **kwargs)
      return helper

    """
    Service functions.
    """

    def test_connect(self, discussion_id):
        try:
          self._get(discussion_id).get()
          return None, None
        except DoesNotExist:
          return Errors.BAD_DISCUSSION_ID 

    @_check_discussion_id
    def create_user(self, discussion_id, nickname, user_id=None):
        discussion = self._get(discussion_id)
        if len(discussion.filter(users__name=nickname)) > 0:
          return Errors.NICKNAME_EXISTS 

        if user_id is not None:
          user_ref = self._get_user_ref(discussion_id, user_id)
          if len(user_ref) > 0:
            return Errors.USER_ID_EXISTS 

        unit_id = discussion.get().document
        cursor = Cursor(unit_id=unit_id, position=-1) 
        user = User(
          name=nickname,
          viewed_unit=unit_id,
          start_time=datetime.utcnow(), #.strftime(constants.DATE_TIME_FMT),
          cursor=cursor
        ) 
        if user_id is not None: # use pre-chosen id
          user.id = user_id

        #### MONGO
        discussion.update(push__users=user)
        #### MONGO

        response = {"user_id": user.id}
        return response, None

    @_check_discussion_id
    @_check_user_id
    def load_user(self, discussion_id, user_id):
        discussion = self._get(discussion_id).get()
        user = self._get_user(discussion_id, user_id)

        doc_meta_ids = []
        chat_meta_ids = []

        cursors = []
        for p in discussion.users:
          if p.active:
            cursors.append({
              "user_id": p.id,
              "nickname": p.name, 
              "cursor": p.cursor.to_mongo().to_dict()
            })
          doc_meta_ids.append(p.cursor.unit_id)

        timeline = []
        for i in user.get().timeline: 
          timeline.append({
            "unit_id": i.unit_id,
            "start_time": i.start_time.strftime(constants.DATE_TIME_FMT),
            "end_time": i.end_time.strftime(constants.DATE_TIME_FMT),
          })
          doc_meta_ids.append(i.unit_id)

        unit_ids = []
        for u in discussion.chat:
          unit = self._get_unit(u).get()
          unit_ids.append(u)
          unit_ids += unit.forward_links 
        unit_ids = list(set(unit_ids))

        for u in unit_ids: # chat units and forward links
          unit = self._get_unit(u).get()
          chat_meta_ids.append(u)

        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)
        chat_meta = self._chat_metas(discussion_id, chat_meta_ids)

        response = {
          "nickname": user.get().name,
          "cursors": cursors,
          "current_unit": user.get().viewed_unit, 
          "timeline": timeline,
          "chat_history": list(discussion.chat), 
          "chat_meta": chat_meta,
          "doc_meta": doc_meta
        }
        return response

    @_check_discussion_id
    def join(self, discussion_id, user_id):
        """
        Update start time of current unit.
        """
        user_ref = self._get_user_ref(discussion_id, user_id)
      
        #### MONGO
        user_ref.update(
          set__users__S__active=True,
          set__users__S__start_time=
            datetime.utcnow()
        ) 
        #### MONGO

        response = self.load_user(discussion_id=discussion_id, user_id=user_id)
        user = self._get_user(discussion_id, user_id)
        cursor_response = {
          "user_id": user_id,
          "nickname": user.get().name,
          "cursor": user.get().cursor.to_mongo().to_dict()
        }
        return response, [cursor_response]

    @_check_discussion_id
    @_check_user_id
    def leave(self, discussion_id, user_id):
        """
        Create new time interval for last visited unit.
        """
        user = self._get_user(discussion_id, user_id)
        editing_locks = user.get().editing
        position_locks = user.get().moving

        #### MONGO
        for e in editing_locks:
          self._release_edit(discussion_id, user_id, e)
        for p in position_locks:
          self._release_position(discussion_id, user_id, p)
        self._time_entry(discussion_id, user_id)
        user_ref = self._get_user_ref(discussion_id, user_id)
        user_ref.update(
          set__users__S__active=False
        ) 
        #### MONGO

        user = self._get_user(discussion_id, user_id)
        response = {
          "user_id": user_id,
          "nickname": user.get().name
        }
        return None, [response]

    # TODO: MULTIPLE MONGO OPERATIONS
    @_check_discussion_id
    @_check_user_id
    @_check_unit_id
    def load_unit_page(self, discussion_id, user_id, unit_id):
        """
        This is the trigger for updating the timeline.
        """
        user_ref = self._get_user_ref(discussion_id, user_id)

        # perform unit-based operations
        unit = self._get_unit(unit_id).get()

        doc_meta_ids = []
        doc_meta_ids.append(unit_id)
        for c in unit.children:
          c_unit = self._get_unit(c).get()
          doc_meta_ids.append(c)
          for g in c_unit.children:
            doc_meta_ids.append(g)
        for b in unit.backward_links:
          b_unit = self._get_unit(b).get()
          doc_meta_ids.append(b)
          for g in b_unit.backward_links:
            doc_meta_ids.append(g)

        #### MONGO
        # update cursor
        user_ref.update(
          set__users__S__cursor__unit_id=unit_id, # new page
          set__users__S__cursor__position=-1 # for now, default to end
        )
        # add entry for old viewed_unit
        time_interval = self._time_entry(discussion_id, user_id)
        # update viewed unit to current
        user_ref.update(
          set__users__S__viewed_unit = unit_id
        )
        #### MONGO

        user = self._get_user(discussion_id, user_id)
        nickname = user.get().name
        cursor = user.get().cursor
        timeline_entry = {
          "unit_id": time_interval.unit_id,
          "start_time": time_interval.start_time.strftime(constants.DATE_TIME_FMT),
          "end_time": time_interval.end_time.strftime(constants.DATE_TIME_FMT),
        }

        # ancestors
        ancestors = self._get_ancestors(unit_id)
        for a in ancestors:
          doc_meta_ids.append(a)

        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)

        response = {
          "ancestors": ancestors,
          "timeline_entry": timeline_entry,
          "doc_meta": doc_meta
        }
        cursor_response = {
          "user_id": user_id,
          "nickname": nickname,
          "cursor": cursor.to_mongo().to_dict(),
        }

        return response, [cursor_response]

    @_check_discussion_id
    @_check_unit_id
    def get_ancestors(self, discussion_id, unit_id):
        ancestors = self._get_ancestors(unit_id)

        doc_meta_ids = []
        for a in ancestors:
          doc_meta_ids.append(a)

        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)

        response = {
          "ancestors": ancestors,
          "doc_meta": doc_meta
        }
        return response, None

    @_check_discussion_id
    @_check_unit_id
    def get_unit_content(self, discussion_id, unit_id):
        unit = self._get_unit(unit_id).get()
        response = {
          "pith": unit.pith,
          "hidden": unit.hidden
        }
        return response, None
  
    @_check_discussion_id
    @_check_unit_id
    def get_unit_context(self, discussion_id, unit_id):
        """
        Make sure the unit is in the document.
        """
        unit = self._get_unit(unit_id).get()
        in_chat = unit.in_chat
        if in_chat:
          doc_meta = self._chat_meta(discussion_id, unit_id)
          response = {
            "in_chat": in_chat,
            "doc_meta": doc_meta,
          }
        else:
          chat_meta = self._doc_meta(discussion_id, unit_id)
          response = {
            "in_chat": in_chat,
            "chat_meta": chat_meta,
          }
        return response, None

    @_check_discussion_id
    @_check_user_id
    def post(self, discussion_id, user_id, pith):
        discussion = self._get(discussion_id)

        chat_meta_ids = []
        doc_meta_ids = []

        forward_links = self._retrieve_links(pith)
        for f in forward_links:
            unit = self._get_unit(f)
            if unit.get().in_chat:
              chat_meta_ids.append(f)
            else:
              doc_meta_ids.append(f)

        unit = Unit(
          pith=pith,
          discussion=discussion_id,
          parent="",
          author=user_id,
          in_chat=True,
          forward_links=forward_links,
          original_pith=pith,
        )
        unit_id = unit.id

        #### MONGO
        unit.save()
        discussion.update(push__chat=unit_id)
        #### MONGO

        chat_meta_ids.append(unit_id)

        # make backlinks
        for f in forward_links:
          self._get_unit(f).update(
            push__backward_links = unit_id
          )
          unit = self._get_unit(f)
          if unit.get().in_chat:
            chat_meta_ids.append(f)
          else:
            doc_meta_ids.append(f)

        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)
        chat_meta = self._chat_metas(discussion_id, chat_meta_ids)

        response = {
          "unit_id": unit_id,
        }
        return None, [response, doc_meta, chat_meta]

    @_check_discussion_id
    def search(self, discussion_id, query):
        """
        https://docs.mongodb.com/manual/reference/operator/query/text/
        """
        # by default, only search within own discussion
        results = Unit.objects()._collection.find({
          "discussion": discussion_id, "$text": {"$search": query}
        })
        results = [r for r in results]

        chat_meta_ids = []
        doc_meta_ids = []

        # TODO: don't show if hidden
        for unit in results: # dict form
          unit_id = unit["_id"]
          if unit["in_chat"]:
            chat_meta_ids.append(unit_id)
          else:
            doc_meta_ids.append(unit_id)

        chat = [{"unit_id": c} for c in chat_meta_ids] 
        doc = [{"unit_id": d} for d in doc_meta_ids] 

        # TODO should depend on discussion!
        chat_meta = self._chat_metas(discussion_id, chat_meta_ids)
        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)

        response = {
          "chat_units": chat,
          "doc_units": doc,
          "chat_meta": chat_meta,
          "doc_meta": doc_meta
        }
        return response, None
      
    @_check_discussion_id
    @_check_unit_id
    def send_to_doc(self, discussion_id, user_id, unit_id):
        """
        NOTE: 
        The document unit does not copy over the chat unit's backward links.
        Instead, we have a pointer to the chat unit, so we can use that to find
        "backlinks".
        """
        user = self._get_user(discussion_id, user_id)
        chat_unit = self._get_unit(unit_id).get()

        position = user.get().cursor.position if user.get().cursor.position != -1 else \
          len(self._get_unit(user.get().cursor.unit_id).get().children)
        parent_id = user.get().cursor.unit_id

        # remove chat links
        pith = self._remove_chat_links(chat_unit.pith)
        forward_links = self._retrieve_links(pith)

        unit = Unit(
          pith=chat_unit.pith,
          discussion=discussion_id,
          forward_links=forward_links,
          parent=parent_id,
          source_unit_id=unit_id, # from chat
          original_pith=chat_unit.pith,
        )
        unit_id = unit.id

        parent = self._get_unit(parent_id)
        key = "push__children__{}".format(position)

        #### MONGO
        unit.save()
        parent.update(**{key: [unit_id]})
        #### MONGO

        doc_meta_ids = []
        chat_meta_ids = []
        doc_meta_ids.append(unit_id)
        doc_meta_ids.append(parent_id)

        for f in forward_links:
          unit = self._get_unit(f)
          if unit.get().in_chat:
            chat_meta_ids.append(f)
          else:
            doc_meta_ids.append(f)

        for f in forward_links:
          self._get_unit(f).update(
            push__backward_links = unit_id
          )
          doc_meta_ids.append(f)

        response = {"unit_id": unit_id}
        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)
        chat_meta = self._chat_metas(discussion_id, chat_meta_ids)
        
        return None, [response, doc_meta, chat_meta]

    @_check_discussion_id
    @_check_user_id
    @_check_unit_id
    @_verify_position
    def move_cursor(self, discussion_id, user_id, unit_id, position):
        user_ref = self._get_user_ref(discussion_id, user_id)

        #### MONGO
        user_ref.update(
          set__users__S__cursor__unit_id=unit_id,
          set__users__S__cursor__position=position
        )
        #### MONGO

        user = self._get_user(discussion_id, user_id)
        response = {
            "user_id": user_id,
            "nickname": user.get().name,
            "cursor": user.get().cursor.to_mongo().to_dict()
        }
        return None, [response]

    @_check_discussion_id
    @_check_unit_id
    def hide_unit(self, discussion_id, unit_id):
        """
        Not a locked operation, so may hide a unit being edited/moved.
        """
        tree = self._get_tree(unit_id)

        #### MONGO
        for t in tree:
          unit = self._get_unit(t)
          unit.update(hidden=True)
        #### MONGO

        doc_meta = self._doc_metas(discussion_id, tree)
        return None, [doc_meta]
        
    @_check_discussion_id
    @_check_unit_id
    def unhide_unit(self, discussion_id, unit_id):
        tree = self._get_tree(unit_id)

        #### MONGO
        for t in tree:
          unit = self._get_unit(t)
          unit.update(hidden=False)
        #### MONGO
        
        doc_meta = self._doc_metas(discussion_id, tree)
        return None, [doc_meta]

    @_check_discussion_id
    def add_unit(self, discussion_id, pith, parent, position):
        """
          Try to use previous to place new unit, otherwise use position.
          Releases edit lock.
        """
        forward_links = self._retrieve_links(pith)
        if self._contains_chat_link(forward_links):
          return Errors.INVALID_REFERENCE

        unit = Unit(
          pith=pith,
          discussion=discussion_id,
          forward_links=forward_links,
          parent=parent,
        )
        unit_id = unit.id

        parent_ptr = self._get_unit(parent)
        key = "push__children__{}".format(position)

        #### MONGO
        unit.save()
        parent_ptr.update(**{key: [unit_id]})
        #### MONGO

        doc_meta_ids = []
        chat_meta_ids = []
        doc_meta_ids.append(unit_id)
        doc_meta_ids.append(parent)

        for f in forward_links:
          unit = self._get_unit(f)
          if unit.get().in_chat:
            chat_meta_ids.append(f)
          else:
            doc_meta_ids.append(f)

        # make backlinks
        for f in forward_links:
          self._get_unit(f).update(
            push__backward_links = unit_id
          )
          unit = self._get_unit(f)
          if unit.get().in_chat:
            chat_meta_ids.append(f)
          else:
            doc_meta_ids.append(f)

        response = {"unit_id": unit_id}
        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)
        chat_meta = self._chat_metas(discussion_id, chat_meta_ids)

        return None, [response, doc_meta, chat_meta]

    # TODO: might support multi-select
    @_check_discussion_id
    @_check_user_id
    @_check_unit_id
    def select_unit(self, discussion_id, user_id, unit_id):
        """
          Takes position lock.
        """
        unit = self._get_unit(unit_id) 
        if unit.get().position_privilege is not None: 
          return Errors.FAILED_POSITION_ACQUIRE 

        #### MONGO
        self._acquire_position(discussion_id, user_id, unit_id)
        #### MONGO

        doc_meta = self._doc_metas(discussion_id, [unit_id])
        return None, [doc_meta]

    @_check_discussion_id
    @_check_user_id
    @_check_unit_id
    @_verify_positions_privilege
    def deselect_unit(self, discussion_id, user_id, unit_id):

        #### MONGO
        self._release_position(discussion_id, user_id, unit_id)
        #### MONGO

        doc_meta = self._doc_metas(discussion_id, [unit_id])
        return None, [doc_meta]

    # TODO: MULTIPLE MONGO OPERATIONS
    @_check_discussion_id
    @_check_user_id
    @_check_units
    @_verify_positions_privilege
    @_verify_parent
    def move_units(self, discussion_id, user_id, units, parent, position):
        """
          Releases position lock.
          Removes each of the units from old parent and puts under new parent.
        """
        doc_meta_ids = []

        # remove from old
        for unit_id in units:
          unit = self._get_unit(unit_id)
          old_parent = unit.get().parent
          self._get_unit(old_parent).update(
            pull__children=unit_id
          )
          doc_meta_ids.append(old_parent)

        # add to new
        key = "push__children__{}".format(position)
        parent_ptr = self._get_unit(parent)
        parent_ptr.update(**{key: units})
        for unit_id in units:
          unit = self._get_unit(unit_id)
          unit.update(
            set__parent=parent,
          )
          self._release_position(discussion_id, user_id, unit_id)
        doc_meta_ids.append(parent)

        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)
      
        return None, [doc_meta]

    # TODO: MULTIPLE MONGO OPERATIONS
    @_check_discussion_id
    @_check_user_id
    @_check_units
    @_verify_positions_privilege
    @_verify_parent
    def merge_units(self, discussion_id, user_id, units, parent, position):
        """
          Releases position lock.
          Removes each of the units from old parent and puts under new parent.
        """
        added_unit_response = self.add_unit(
          discussion_id=discussion_id, pith="", 
          parent=parent, position=position
        )[1] 
        added_unit = added_unit_response[0]
        doc_meta = added_unit_response[1]
        unit_id = added_unit["unit_id"]

        move_units_response = self.move_units(discussion_id=discussion_id, user_id=user_id, units=units, 
          parent=unit_id, position=0)[1] # put at head
        doc_meta2 = move_units_response[0]

        # get most up-to-date information
        doc_meta_ids = [d["unit_id"] for d in doc_meta + doc_meta2]
        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)

        response = {"unit_id": unit_id}

        return None, [response, doc_meta]

    @_check_discussion_id
    @_check_user_id
    @_check_unit_id
    def request_to_edit(self, discussion_id, user_id, unit_id):
        """
          Takes edit lock.
        """
        unit = self._get_unit(unit_id) 
        if unit.get().edit_privilege is not None: 
          return Errors.FAILED_EDIT_ACQUIRE

        #### MONGO
        self._acquire_edit(discussion_id, user_id, unit_id)
        #### MONGO

        doc_meta = self._doc_metas(discussion_id, [unit_id])
        return None, [doc_meta]

    @_check_discussion_id
    @_check_user_id
    @_check_unit_id
    @_verify_edit_privilege
    def deedit_unit(self, discussion_id, user_id, unit_id):
        #### MONGO
        self._release_edit(discussion_id, user_id, unit_id)
        #### MONGO

        doc_meta = self._doc_metas(discussion_id, [unit_id])
        return None, [doc_meta]

    # TODO: MULTIPLE MONGO OPERATIONS
    @_check_discussion_id
    @_check_user_id
    @_check_unit_id
    @_verify_edit_privilege
    def edit_unit(self, discussion_id, user_id, unit_id, pith):
        """
          Releases edit lock.
        """
        forward_links = self._retrieve_links(pith)
        if self._contains_chat_link(forward_links):
          return Errors.INVALID_REFERENCE

        unit = self._get_unit(unit_id) 
        old_forward_links = unit.get().forward_links

        unit.update(
          pith=pith, 
          forward_links=forward_links,
          edit_count=unit.get().edit_count + 1 # increment
        )

        # handle backlinks
        removed_links = set(old_forward_links).difference(set(forward_links)) 
        for r in removed_links: # remove backlink 
          unit = self._get_unit(r).update(
            pull__backward_links = unit_id
          )
        added_links = set(forward_links).difference(set(old_forward_links))
        for a in added_links: # add backlink 
          unit = self._get_unit(a).update(
            push__backward_links = unit_id
          )

        doc_meta_ids = []
        chat_meta_ids = []
        doc_meta_ids.append(unit_id)

        # backward links added/removed
        for b in removed_links.union(added_links):
          unit = self._get_unit(b)
          if unit.get().in_chat:
            chat_meta_ids.append(b)
          else:
            doc_meta_ids.append(b)

        doc_meta = self._doc_metas(discussion_id, doc_meta_ids)
        chat_meta = self._chat_metas(discussion_id, chat_meta_ids)

        return None, [doc_meta, chat_meta]

    def test(self, a):
      return a

    async def call_test(self):
      print("1")
      job = await self.redis_queue.enqueue_job("test", 4)
      print("2")
      print("result", await job.result(timeout=3))

#     def export_unit_tree(self, unit_id):
# 
#     def export_units(self, units, method):
#       """
#       method = doc, pdf, raw, html
#       """
#       doc = []
#       for unit_id in units:
#         doc.append(self.export_unit_tree(unit_id))
#       # process doc according to method
#       # call function to upload
# 
#     def export_document(self, discussion_id, method):
#       """
#       method = doc, pdf, raw, html
#       """
#       discussion = self._get(discussion_id).get()
#       root = discussion.document
#       doc = self.export_unit_tree(root)
#       # process doc according to method
#       # call function to upload
