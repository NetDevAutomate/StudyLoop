# AI Usage
<!-- facts: F3 F10 -->

Using an AI assistant to contribute is welcome on two conditions: you review and understand everything
you submit, and you say that the assistant helped. The reviewer holds AI-written code to exactly the
same bar as any other: tests that fail on revert, documentation that is true.

## Disclose it

1. **In the pull request**, under question 2 of the five-question description ("What changed?"):
   one line naming the assistant and what it drafted, for example *AI assistance: Claude Code drafted
   the first version of the test and the migration; I rewrote the assertions.* The five questions are
   on [Raising a pull request](contributor-pull-requests.md).
2. **In the commit**, with a `Co-Authored-By:` trailer at the end of the body. The trailer is the
   convention this repository's own history uses; you remain the author who reviewed the change and
   stands behind it:

    ```text
    fix(<scope>): <what the change makes true>

    <Why it was wrong, and what is now true -- not a restatement of the diff.>

    Co-Authored-By: <assistant name> <noreply@example.com>
    ```

3. **Nowhere else.** Keys, transcripts and prompts stay out of the pull request, the issue and the repository.

Disclosure is not a confession; an undisclosed assistant is a review the maintainer did not know to do.

## Own the result

1. **Read every line** before you stage it. If you cannot explain a line, delete it or learn it first.
2. **The test fails on revert.** An assistant that writes the fix and the test together often writes a
   test that passes without the fix; revert the fix locally and watch the test fail for the reason you
   meant (see [Write a test that can catch the bug](contributor-testing.md#write-a-test-that-can-catch-the-bug)).
3. **Receipts, not claims.** Under question 3 paste the commands you ran and their actual output,
   including skips and failures. A sentence the assistant wrote about a command it did not run is not
   evidence; the drift tests in `packages/studyloop/tests/test_docs_drift.py` exist because such
   sentences get into documentation.
4. **Cite `file:line`**, not the assistant's summary. Reviewers verify claims against the code.
5. **Models fabricate history.** Commit shas, test counts and "this was already fixed in" statements
   are checked by hand before they go into a page or a description.

## Models through a LiteLLM gateway

StudyLoop chooses a model in two independent places, and neither is hard-coded to a vendor:

1. **Mentor harnesses** bring their own model access; StudyLoop launches them and never sees their
   credentials. To route a harness through a gateway, configure the harness itself as its own
   documentation describes. Nothing in this repository changes.
2. **Content generation** (flashcards, quizzes) uses the provider registry in
   `packages/studyloop/src/studyloop/content/generators/provider_profiles.py`. Each row binds a slug to
   an adapter (`openai_compat`, `anthropic_compat`, `bedrock`, `ollama`), a base URL, the environment
   variable that carries its key, and a curated model list. The active row is chosen by the
   `card_generator:` block in `config.yaml` (`backend`, `provider`, `model`). To see the shipped slugs:

    ```bash
    rg -n 'slug=' packages/studyloop/src/studyloop/content/generators/provider_profiles.py
    ```

A LiteLLM gateway is an OpenAI-compatible proxy that fronts many providers behind one URL and one key.
Because the registry has an `openai_compat` adapter, adding one is the documented extension: a
`ProviderProfile` row with `adapter="openai_compat"`, the proxy's `base_url`, an `auth_env` such as
`LITELLM_API_KEY`, a curated model list, and a line in `.env.example`. Two caveats before you do:

- A row's base URL is fixed in the registry today, so a per-machine proxy address needs an environment
  override that does not exist yet. Open an issue and propose it there first.
- Variables ending `_API_KEY`, `_TOKEN` or `_SECRET` are deliberately scrubbed from every process
  StudyLoop spawns (`packages/studyloop/src/studyloop/session/child_env.py`), so a gateway key set for
  StudyLoop never reaches a mentor child. That is a feature, not a bug to work around.

The one place a gateway already works without a code change is the acceptance tier's `gateway`
learner actor, which reads `LITELLM_API_KEY`, `LITELLM_BASE_URL` and `STUDYLOOP_ACC_GATEWAY_MODEL`
from the environment; see [the learner actors](acceptance-testing.md#the-learner-actors). Never commit
a gateway hostname, port or key: read them from the environment and keep the values in your untracked `.env`.

## Multi-model review, if you run one

Large changes to this project have been read by several models from different families through such a
gateway before a human read them, each claim checked against the source. That is optional practice,
not a requirement. If you do it: cite only the findings you verified, name the `file:line` each one
rests on, and keep keys and transcripts out of the pull request.
