# Data model decisions (Delivery 1)

| Decision | Problem it prevents |
|---|---|
| UUID primary keys | Enumeration of ids by incrementing a number in a URL. |
| `CHECK (email = lower(email))` + unique | Two accounts for `Ana@x.com` and `ana@x.com`, even if some code path forgets to normalize. |
| `memberships` with composite PK `(user_id, workspace_id)` | The same user holding two roles in one workspace. |
| Role as `CHECK`-constrained text | An invalid role written by a bug or a manual query. |
| `UNIQUE (workspace_id, name)` on categories | Duplicate category names inside a workspace, without blocking the same name in another. |
| `UNIQUE (workspace_id, id)` on categories | Prepares the composite FK that issues will use so an issue cannot point to another workspace's category. |
| Hashed session ids | A database leak handing out working session tokens. |
| Repositories require `workspace_id` | A query that fetches a workspace-owned row by id alone. |
| Non-member and missing resource both return 404 | Revealing that a workspace or resource exists. |
