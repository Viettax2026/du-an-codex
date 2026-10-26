# Public library research: group member enumeration

Reviewed on 2026-10-26. This research inspected published source code without
executing package installers or contacting Zalo or AkaBiz with customer sessions.

## Sources inspected

| Package | Version | Relevant behavior |
| --- | --- | --- |
| zca-js | 2.2.0 | Existing `getGroupInfo` uses `getmg-v2`; invite information uses `link/ginfo(memberPage)`. |
| @softtynet/zca-js | 2.3.7 | Adds `getGroupInfoV2(groupId, {mpage, mcount})`, a read of group information and members by group ID. |
| zca-js-vnzl | 2.1.2 | Inspected group information and invite methods follow the existing approach. |
| new-zca-js | 0.0.4 | Inspected group information and invite methods follow the existing approach. |
| bonz-sdk | 1.8.1 | Wrapper around zca-js; no alternative member enumeration was identified in the inspected package. |
| zlapi (Python) | 1.0.3 | `fetchGroupInfo` also uses `getmg-v2`; no additional group-member paging method was identified in the inspected source. |

Metadata and tarballs came from the public npm registry; all four additionally
downloaded package archives matched their registry SHA-512 integrity values.
The GitHub source links declared by the Softtynet package returned 404 during
this review, so the evidence for that method is the published npm archive,
including its types, implementation and license. The fork was not installed.
The Python source distribution was read without installation and matched its
PyPI SHA-256 digest.

Reference: https://registry.npmjs.org/@softtynet/zca-js/2.3.7

## Candidate read method

The referenced method issues an authenticated GET to the group service's
`/api/group/getgi/v2` endpoint with an encrypted payload containing `grid`,
`mpage`, `mcount`, avatar sizes and the session's existing device identifier.
Its response is typed as group information with `currentMems`, `memberIds`,
`totalMember` and `hasMoreMember`. This is a different read from both sources
previously tried by ZaloFlow.
The package's protocol constants specify type 30 and version 689. The adapter
sets version 689 on this read only; the existing session and other SDK calls
retain their current configuration.

ZaloFlow now tries this source when the initial member list is incomplete,
using only the current session and only a group found in that account's joined
group list. It requests at most 100 members per page. It does not alter group
settings, enable invite links, join groups, change identity or elevate roles.
An initial failure or partial response preserves known IDs and allows the
existing read sources to supply their available data; a failed continuation
retains its cursor and saved rows for retry. Group IDs in returned data must
match the selected group. Diagnostics keep counts and fixed outcomes only.

## Validation and limits

Offline tests validate serialization/encryption with the pinned SDK, error
propagation, joined-group boundaries, page cursors, duplicate handling and a
synthetic 645-member result across seven pages. No live customer group or
account was tested. Public source availability does not establish that this
method returns hidden community members for every account, or that AkaBiz uses
it. Permission errors, truncated data and repeated pages must remain partial
results rather than being reported as a successful full scan.
