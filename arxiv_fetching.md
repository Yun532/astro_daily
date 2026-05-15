# arXiv Fetching Modes

Astro Daily uses separate source strategies for different data sizes.

## Daily report mode

Use `sources.arxiv.fetch_mode: daily_listing`.

This is the default mode. The pipeline first reads:

```text
https://arxiv.org/list/<category>/new
```

It extracts the exact paper IDs from the daily "new" and "cross" sections, then calls the arXiv API with `id_list` to fetch metadata for only those papers.

This is the best fit for a daily report because it avoids broad category searches such as `cat:astro-ph.HE&max_results=120` when the listing page already tells us the exact IDs.

## Category search mode

Use `sources.arxiv.fetch_mode: category_search`.

This keeps the older behavior:

```text
search_query=cat:<category>&sortBy=submittedDate&sortOrder=descending
```

Use this when you intentionally want a rolling window of recent papers, including backfill from previous days. It is more likely to hit rate limits than daily listing mode, especially across many categories.

## Daily mode with backfill

Use:

```yaml
sources:
  arxiv:
    fetch_mode: daily_listing
    backfill_with_category_search: true
```

This fetches today's listing IDs first, then also performs category search for older recent candidates. It gives the richest candidate pool, but costs more API requests.

## On-demand backfill

Use:

```yaml
sources:
  arxiv:
    fetch_mode: daily_listing
    backfill_with_category_search: false
    on_demand_backfill_with_category_search: true
```

This is the default daily-report behavior. The run first scores today's listing papers. If the selected regular papers are fewer than `scoring.same_day_target`, the pipeline performs a category search backfill and scores only the newly added candidates. This keeps normal daily runs lightweight while still giving the report a pool of valuable older papers when the daily batch is thin or low-scoring.

## Historical bulk metadata

Do not use the daily pipeline for large historical metadata pulls. Use arXiv OAI-PMH instead:

```text
https://oaipmh.arxiv.org/oai?verb=ListRecords&metadataPrefix=arXivRaw&set=physics:astro-ph
```

Store the returned `resumptionToken` and resume until exhausted. This is the appropriate path for large metadata archives; the daily pipeline should stay small, cached, and polite.
