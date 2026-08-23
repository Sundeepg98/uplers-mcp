"""A PRESENCE-BASED build of this server's auth verdict, for showing it can fail.

WHY THIS FILE IS IN THE REPO
----------------------------
``tests/test_session_lifecycle.py`` asserts that ``uplers_session_info`` gets
its ``authenticated`` verdict from a real request and never from the token
sitting on disk. That assertion is only worth anything if it is capable of
going red -- and a run of defects in this family of repos in one week were
checks that could not fail. A test that has never been shown failing is a
claim, not a measurement.

This pytest plugin re-creates the exact bug those tests exist to catch, and it
is not a hypothetical one. The sibling Instahyre server SHIPPED it: a login
tool that returned success the moment a ``sessionid`` cookie appeared. Django
hands those to anonymous visitors, so the condition was already true while the
login page was still painting; the window closed before the operator could type
and the tool reported ``authenticated: true`` while every real call 401'd.

Uplers carries the identical trap in different clothes. Its bundle reads
``localStorage["token"] ?? localStorage["guest_token"]``, and ``guest_token``
is ANONYMOUS, so a token here can be present and belong to nobody. Here that is
reproduced by replacing ``uplers_server.session.check_auth`` with a build that
never leaves the process: it answers ``authenticated`` straight from
``client.has_token()``, which is precisely "a credential exists" promoted into
"a session works".

HOW TO RUN IT
-------------
    PYTHONPATH=scripts pytest tests/test_session_lifecycle.py -p presence_is_auth_control

    # PowerShell
    $env:PYTHONPATH="scripts"; venv/Scripts/python -m pytest tests/test_session_lifecycle.py -p presence_is_auth_control

MEASURED 2026-08-23, against the commit that introduced the two tools::

    4 failed, 35 passed

    FAILED TestTheVerdictComesFromTheProbe::test_a_guest_200_is_null_not_false_and_not_true
    FAILED TestTheVerdictComesFromTheProbe::test_a_transport_failure_is_null_with_the_reason_attached
    FAILED TestTheVerdictComesFromTheProbe::test_a_401_with_a_token_present_is_a_real_false
    FAILED TestTheVerdictComesFromTheProbe::test_a_real_yes_is_a_yes_and_says_where_it_came_from

Those four are the whole honesty claim of the file, and reading WHY each one
dies is the point:

* the guest-200 case is the shipped bug exactly -- a token is present, the
  route answers 200 with no ``talent_details``, and the permissive build calls
  that a signed-in session where the real one says null;
* the transport-failure case is the same substitution under a different cause
  -- the network is down, nothing was measured, and presence answers anyway;
* the 401 case is the most expensive of the three above, because it inverts a
  *correct* refusal: Uplers said no, and a presence build says yes;
* the fourth was not predicted and is the most interesting. It asserts
  ``signed_in_as == "Sundeep G"`` on a genuine yes, and it dies with a
  ``KeyError`` because a presence build has no response body to read a name
  out of. That is the property stated from the other side: a true verdict here
  is not merely a boolean, it CARRIES the evidence that produced it, and a
  build that cannot produce the evidence cannot fake the verdict past this
  line either.

The 35 that survive are supposed to survive, and the asymmetry is the property
worth having:

* every ``verify_live=False`` test stays green, because that path never asks
  ``check_auth`` at all -- it is offline by construction and null by design;
* every expiry test stays green, because ``credential_report`` reads the token
  and never the verdict, so a broken verdict cannot move it;
* ``test_no_token_and_a_401_is_false_not_null`` stays green on purpose: with no
  token stored, presence and truth agree, so that case cannot distinguish the
  builds. It is the file's own control against a suite that merely asserts
  "everything is null", which would pass under any build at all;
* the leak sweep stays green, because a permissive verdict does not print a
  token -- the two defects are independent and this file only re-creates one.

RUN IT AGAINST tests/ ENTIRE and eighteen further tests go red, all of them
asserting the same property about the same function. That is correct, not
collateral -- ``check_auth`` is the single source of the verdict for the whole
server, so a permissive build of it should bite everywhere the verdict is
claimed. MEASURED 2026-08-23::

    PYTHONPATH=scripts pytest tests -p presence_is_auth_control
    -> 22 failed, 961 passed

    8  tests/test_auth.py            the login handshake and its refresh path,
                                     whose completion condition IS check_auth
    7  tests/test_session.py         check_auth's own unit tests, red by
                                     definition since it is the thing replaced
    4  tests/test_session_lifecycle.py   the four listed above
    3  tests/test_talent_tools.py    uplers_auth_status's three honesty tests

The clean run of the same suite is 983 passed. The 961 above is not a
different suite; it is this one with 22 of its assertions correctly refusing a
verdict that was never measured.

RE-MEASURED 2026-08-23 after `renewal.session_lapses_at` added seven tests to
the file. The SAME four fail and the count of reds does not move, which is the
property worth reading: the new seven pin what a NO-RENEWAL platform reports
about when the operator must sign in by hand, and a broken verdict cannot move
that -- `_renewal` is handed the credential block, never the verdict.

RE-MEASURED AGAIN 2026-08-23 after `renewal.uses_browser` / `renewal.mechanism`
added two more. Still the same four, for the same structural reason::

    tests/test_session_lifecycle.py   4 failed, 37 passed
    tests/ entire                    22 failed, 963 passed
    tests/ entire, control OFF                 985 passed

WHAT THIS FILE IS NOT
---------------------
It is not a fixture and nothing imports it. It is loaded only by ``-p`` on an
explicit command line, so it cannot affect an ordinary run, CI, or a developer
who has never heard of it.
"""


def pytest_sessionstart(session):
    from uplers_server import endpoints, session as session_mod

    async def presence_is_auth(client):
        """The bug: `authenticated` straight from "is there a credential".

        No request is made. Note what this cannot express -- there is no way
        to return None from here, because presence is a boolean and the whole
        defect is that it has no third state for "I could not tell".
        """
        has_token = client.has_token()
        return {
            "authenticated": has_token,
            "token_present": has_token,
            "checked_against": endpoints.AUTH_PROBE_NOTE,
            "reason": None if has_token else "No Uplers token stored.",
        }

    session_mod.check_auth = presence_is_auth
    print(
        "\n[presence_is_auth_control] check_auth now answers from "
        "client.has_token() -- the shipped Instahyre bug shape, no request made"
    )
