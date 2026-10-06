# Resource Server — Agent Skill Specification

What the agent skill (`SKILL.md`) must do. It is part of the
[high-level specification](high_level_spec.md); the features, rules, and limits it refers
to are defined there.

## Purpose
- The project includes a skill, `SKILL.md`, that teaches AI agents how to use the service on
  their own, without human help.
- The skill is one self-contained file that can be copied as-is into an agent's skills
  folder. It needs only a POSIX shell and `curl`.

## Finding the service
- The skill must locate the service rather than assume it runs on the agent's own machine.
- It resolves the service's base URL in this order, using the first one whose status check
  answers:
  1. a URL the user gave;
  2. the URL cached by an earlier run;
  3. the known locations of the home server, `http://raspberry-server.local:3100` and then
     `http://192.168.0.2:3100`;
  4. otherwise it asks the user for the address.
- The working URL is cached in `${XDG_CACHE_HOME:-$HOME/.cache}/resources-server/base_url`.
- Links handed to the user are the ones the service returns for that base URL, so they work
  for other people on the network.

## What the skill covers
- One section per feature of the service:
  - uploading a file or generated content, including how to say what kind of content it is;
  - replacing a resource under the same link;
  - browsing all resources and checking the service's status;
  - managing the service (start, stop, restart, status, logs, tests) with the entry point
    `init.sh`, on the machine that runs it, and troubleshooting common problems such as the
    service not answering or its address already being in use.
- It points to the OpenAPI document at `/api/openapi.json` as the full and authoritative API
  description, and does not repeat what that document already says (response fields,
  status codes, schemas). It keeps only what an agent needs to act.
- It uses the `/api/` addresses only.
- It states the same rules as the specification: the 10 MB file limit, the 24-hour
  lifetime, temporary storage, and open access where anyone can overwrite any resource.
- It only describes actions the service actually supports. In particular, it must not offer
  deleting a resource.
- It tells the agent to ask the user before any management command that discards
  resources.

## Staying in step
- Whenever a feature, rule, or limit changes, the skill is updated at the same time.
- Automated tests check the skill against the service and fail when:
  - a supported action or management command is missing from it;
  - it offers an action the service does not support;
  - a size or lifetime it states differs from the service's, including any extra value;
  - it uses an address outside `/api/`;
  - it needs a program other than `sh` and `curl`.
