import { boardSocket as socket } from "./socket";
import { cleanUpRequest, createRequestWrapper } from "./queue";
import { getValue, setValue } from "../api/local";
import { getStatus } from "./utils";
import { CREATE_DISCUSSION } from "./types";
import { POPULATE_DISCUSSIONS, ADD_DISCUSSION } from "../reducers/types";

const discKey = "pithDiscussions";

const getLocalDiscussions = (requestId) => {
  return (dispatch) => {
    const discArray = getValue(discKey);
    dispatch({
      type: POPULATE_DISCUSSIONS,
      payload: {
        arr: discArray || [],
      },
    });
  };
};

const createDiscussion = (requestId) => {
  return (dispatch) => {
    const data = {};

    // call backend
    const [startRequest, endRequest] = createRequestWrapper(
      CREATE_DISCUSSION,
      dispatch,
      requestId
    );

    startRequest(() =>
      socket.emit("create", data, (res) => {
        const response = JSON.parse(res);
        const statusCode = getStatus(response, dispatch, {});
        if (statusCode === null) {
          const saved = {
            id: response.discussion_id,
            createdAt: new Date(),
          };

          // save locally
          const discArray = getValue(discKey);

          if (discArray === null) {
            setValue(discKey, [saved]);
          } else {
            discArray.push(saved);
            setValue(discKey, discArray);
          }

          dispatch({
            type: ADD_DISCUSSION,
            payload: {
              add: saved,
            },
          });
        }
        endRequest(statusCode);
      })
    );
  };
};

export { getLocalDiscussions, createDiscussion };
