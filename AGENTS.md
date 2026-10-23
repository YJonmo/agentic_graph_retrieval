# Entity Graphs - market graph case study

**AI tools are expected, not tolerated.** Use whatever you normally use. We do ask that you can explain every line you submit.

**Cost:** this should cost under USD $10 in API spend, and a local model is fine if you would rather. Report what you actually spent.

**Infrastructure is not what is being marked.** Run whatever you can stand up fastest, locally or otherwise. Do not lose two hours to Docker. If you spend your budget on setup and have no resolution logic to show, the submission fails on that alone.

**Check the licence on every source before you use it.** Some of the ones listed below are open government data and some are not.

## Context

The hard part is not storing it. It is that no single store handles all of it. Relationships want a property graph, bulk aggregation wants a warehouse, fuzzy candidate retrieval wants a search index, and keeping those consistent is a real problem rather than a deployment detail. On top of that sits the retrieval an AI agent calls, where the naive approach of embedding a subgraph and hoping similarity search finds the right neighbourhood stops working somewhere well below our size.

The other hard part is that most sources worth having carry no shared key. A company register gives you an ACN. An enforcement register gives you a company name in a sentence, and if you attach that notice to the wrong business you have published a false claim that a real company was penalised by a regulator. That case is in this assignment on purpose.

Repository reality: the graph should be built from canonical entities and evidence, not from raw source dumps. The main ingestion artifacts are the canonical entity profiles in `outputs/ingestion/profiles.jsonl`, the link evidence in `outputs/ingestion/links.jsonl`, the source manifest in `outputs/ingestion/source_manifest.json`, and the per-source observations under `outputs/ingestion/observations/`. These should drive the node/edge model, while raw source snapshots remain supporting material for provenance and explainability.

Two things we care about more than most teams:

1. **A wrong link is worse than no link.** A 1% error rate here is millions of specific, confident, false statements about real businesses. We would always rather return nothing.
2. **A merge you cannot undo is a merge you should not have made.** Thresholds get recalibrated. If the source records are gone, so is your ability to change your mind.

You are not being asked to find or map sources. Assume that part is done.

## The sources

Three tiers. They behave differently and the point of the exercise is partly that.

**The more sources you get in, the better. You are not limited to this list.** Take a few from each tier. Which ones you picked and which you left is something we will ask you about, and "I read it and it was not worth the hour" is a good answer.

### Tier 1: identity backbone

- **ABR bulk extract**, `abr.business.gov.au/Tools/BulkExtract`, weekly XML. ABN, entity name, registered business and trading names, ACN where the entity is ASIC-registered, state, ANZSIC, status. This is the large one.
- **ASIC company register** weekly snapshot on `data.gov.au`. ACN, company name, status, type, class, former names.

### Tier 2: keyed attachment

These carry an ABN or ACN some of the time and a name the rest of the time. What "some of the time" means is a number you should report.

- **ASIC AFS Licensee**, `data.gov.au/data/dataset/asic-afs-licensee`. AFS licence number, licensee name, address, authorisations.
- **ASIC Credit Licensee**, `data.gov.au/data/dataset/asic-credit-licensee`. Credit licence number, licensee name.
- **ASIC Banned and Disqualified Organisations**, `data.gov.au/data/dataset/asic-banned-disqualified-org`. Names, ban type, start and end dates.
- **ASIC Liquidator**, `data.gov.au/data/dataset/asic-liquidator`. Registered liquidators and their firms.
- **GLEIF golden copy**. Level 1 gives LEI and legal name. Level 2 gives parent and child relationship records, which is the cleanest hierarchy available to you.


### Tier 3: name-only attachment

No identifier at all. A name in a table, a name in prose, or a name on the cover of a PDF.

- **ACCC infringement notices register**, `accc.gov.au/public-registers/infringement-notices-register`. Web page, not a download. Company names, dates, penalty amounts.
- **TGA Australian Register of Therapeutic Goods**, `tga.gov.au/resources/artg`. Sponsor company names against product entries. There is no clean bulk file; the search visualisation tool exports CSV in four chunks, one per therapeutic type.
- **annualreports.com**, ASX listing at `annualreports.com/Companies?exch=7`. Company names plus PDF annual reports. Subsidiary lists live in the notes to the financial statements.

**There are 1000’s more available at `data.gov.au`**

**Wikidata** via SPARQL is available to you at any tier for aliases, brand names, official websites and parent organisations. Anything else public you want to bring, bring it.

Slice the volume. **Around 1 million entities on the tier 1 side is the target**: enough that a pairwise comparison is off the table and blocking has to be real. An active-status filter plus a state or a couple of ANZSIC divisions gets you roughly there.

## The task
The tasks for this project are broken down in .tasks/todo.md. You will be interactively asked to look into the todo.md and implement every step one by one. 

There are also the outputs provided in the `outputs/ingestion` folder from a previous repository that ingested the data. Your outputs for each part of this repository should go to `outputs/retrieval` folder. 