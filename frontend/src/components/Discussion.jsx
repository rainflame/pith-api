import React, { useState, useEffect } from "react";
import {
    BrowserRouter as Router,
    Switch,
    Route,
    Redirect,
    useRouteMatch,
    useParams,
} from "react-router-dom";

import {
    GENERIC_ERROR,
    INVALID_DISCUSSION,
    NO_USER_ID,
    TAKEN_NICKNAME,
    TAKEN_USER_ID,
} from "../utils/errors";

import { v4 as uuidv4 } from "uuid";
import {
    enterDiscussion,
    createUser,
    joinUser,
    createPost,
    sendToDoc,
    subscribeChat,
    subscribeDocument,
} from "../actions/discussionActions";

import useRequest from "../hooks/useRequest";

import Chat from "./Chat";
import Document from "./Document";
import Menu from "./Menu";
import Search from "./Search";
import DiscussionJoin from "./DiscussionJoin";
import SystemError from "./SystemError";

import DiscussionLayout from "./DiscussionLayout";

const Discussion = (props) => {
    const [chatSearchOpen, setChatSearchOpen] = useState(false);
    const [subscribed, setSubscribed] = useState(false);
    const [query, setQuery] = useState("");

    // request hooks
    const [enterDiscussionStatus, makeEnterDiscussion] = useRequest(
        props.completedRequests
    );
    const [createUserStatus, makeCreateUser] = useRequest(
        props.completedRequests
    );
    const [joinUserStatus, makeJoinUser] = useRequest(props.completedRequests);

    // create status vars for convenience
    const joined = joinUserStatus.made && !joinUserStatus.pending;
    const loading = joinUserStatus.pending;

    const badDiscussion = enterDiscussionStatus.status === INVALID_DISCUSSION;
    const createNickname = enterDiscussionStatus.status === NO_USER_ID;
    const badNickname = createUserStatus.status === TAKEN_NICKNAME;

    const match = useRouteMatch();
    const { discussionId } = useParams();

    useEffect(() => {
        if (!enterDiscussionStatus.made) {
            // we have yet to enter the discussion, so do that now
            makeEnterDiscussion((requestId) =>
                props.dispatch(enterDiscussion(discussionId, requestId))
            );
        } else if (
            !enterDiscussionStatus.pending &&
            !badDiscussion &&
            !joined &&
            !joinUserStatus.pending
        ) {
            // we're done entering the discussion and it's a valid id and we have not yet
            // tried to join with the user
            if (
                enterDiscussionStatus.status === null ||
                createUserStatus.status === null
            ) {
                // if we entered the discussion and it indicated we have a userId already,
                // go ahead and join. Do the same if we just created a nickname sucessfully.
                makeJoinUser((requestId) =>
                    props.dispatch(joinUser(discussionId, requestId))
                );
            }
        }
    });

    const joinDiscussion = (nickname) => {
        // join the discussion with a given nickname
        makeCreateUser((requestId) =>
            props.dispatch(createUser(discussionId, nickname, requestId))
        );
    };

    const chat = (
        <Chat
            loading={loading}
            content={props.chatMap}
            posts={props.posts}
            openSearch={() => setChatSearchOpen(true)}
            closeSearch={() => setChatSearchOpen(false)}
            setQuery={(query) => setQuery(query)}
            addPost={(content) => {
                console.log("posted:", content);
                props.dispatch(createPost(content, uuidv4()));
            }}
            sendPostToDoc={(id) => {
                console.log("moved:", id);
                props.dispatch(sendToDoc(id, uuidv4()));
            }}
        />
    );

    const doc = (
        <Document
            loading={loading}
            units={props.docMap}
            ancestors={props.ancestors}
            currentUnit={props.currentUnit}
            users={props.icons}
            timeline={props.timeline}
        />
    );
    const search = <Search query={query} />;
    const menu = <Menu setDarkMode={props.setDarkMode} />;

    return (
        <Router>
            <SystemError
                error={props.systemError}
                timeout={props.requestTimeout}
            />
            <Switch>
                <Route path={`${match.path}/join`}>
                    {joined ? (
                        <Redirect
                            to={{
                                pathname: `/d/${discussionId}`,
                            }}
                        />
                    ) : (
                        <DiscussionJoin
                            badNickname={badNickname}
                            badDiscussion={badDiscussion}
                            onComplete={(nickname) => joinDiscussion(nickname)}
                            id={discussionId}
                            loadingScreen={loading}
                        />
                    )}
                </Route>
                <Route path={match.path}>
                    {!joined && createNickname && !badDiscussion ? (
                        <Redirect
                            to={{
                                pathname: `/d/${discussionId}/join`,
                            }}
                        />
                    ) : !joined || loading || badDiscussion ? (
                        <DiscussionJoin
                            badDiscussion={badDiscussion}
                            joiningScreen={!joined}
                            loadingScreen={loading}
                        />
                    ) : (
                        <DiscussionLayout
                            chat={chat}
                            document={doc}
                            menu={menu}
                            search={search}
                            searchActive={chatSearchOpen}
                        />
                    )}
                </Route>
            </Switch>
        </Router>
    );
};

export default Discussion;
