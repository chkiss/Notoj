# Core Product Philosophy

* Retrieval over organization
* Search-first workflow
* Capture and retrieval unified into one action
* Notes feel lightweight and disposable
* Plaintext/Markdown as durable long-term storage
* Offline-first
* Keyboard-centric
* Invisible persistence and synchronization
* Minimal cognitive overhead
* External-tool friendly (Vim, Syncthing, CLI)

---

# Tier 1 — Core Identity Features

## Unified Search/Create Interface

* `/` activates incremental search bar
* Live incremental filtering while typing
* Enter opens selected note, or creates a new note titled with the query when no results match
* `n` creates a blank new note directly (explicit shortcut, complementary to search-to-create)
* ESC or Enter exits search mode
* Keyboard-only operation

## Instant Full-Text Search

* Live search updates on every keystroke
* Substring matching
* Fuzzy matching
* Typo tolerance
* Title weighting
* Result ranking by:

  * exact title match
  * partial title match
  * recency
  * body relevance
  * frequency/history

## Plain Filesystem Storage

* Notes stored as `.md` / `.txt`
* Filesystem is source of truth
* Human-readable and externally editable
* No proprietary storage format

## Automatic Title/Filename Derivation

* First line inferred as title
* Slugified filename generation
* Safe rename semantics
* Filename conflict handling

## Autosave

* Continuous autosave
* Save on focus loss
* Crash-safe persistence
* No manual save flow

## Fast Startup and Interaction

* Near-instant launch
* Low-latency typing
* Immediate search responsiveness
* Optimized for rapid capture

## External File Awareness

* Detect:

  * external edits
  * renames
  * deletions
  * Syncthing updates
  * Vim edits
* Automatic reload/update

## Conflict Preservation

* Duplicate conflicting notes instead of silent merge
* Preserve all user text
* Clear conflict naming

## Offline-First Operation

* Fully usable offline
* No cloud dependency
* Sync independent from core operation

---

# Tier 2 — Workflow-Critical Features

## Recent Notes

* Recently modified notes list
* Temporal navigation
* Fast return to active notes

## Session Persistence

* Restore selected note on launch

## Fast Note Switching

* Keyboard navigation between notes
* Quick-open behavior
* Recent-note toggle

## Lightweight Tagging

* Inline hashtags
* Searchable tags
* No dedicated taxonomy UI

## Revision History

* Per-note history
* Snapshot recovery
* Undo across sessions

## Deleted Note Recovery

* Trash system
* Restore support
* Delayed permanent deletion

## Similar/Duplicate Detection

* Similar-title detection
* Duplicate-content detection
* Optional surfacing of related notes

## Deep Keyboard Workflow

* Global shortcuts
* Command-driven navigation
* Minimal mouse dependence

---

# Tier 3 — Engineering-Critical Features

## Incremental Search Indexing

* Filesystem watcher
* Background indexing
* Incremental index updates
* Scales to large note collections

## Atomic File Writes

* Temp-write + rename strategy
* Corruption resistance
* Crash resilience

## Unicode Robustness

* UTF-8 correctness
* Safe filename normalization
* Cross-platform compatibility

## Stable Conflict Semantics

* Deterministic conflict handling
* Predictable naming and recovery

## Large Collection Performance

* Efficient handling of:

  * 10k+
  * 50k+
    notes
* Lazy loading
* Virtualized note lists

## Crash Recovery

* Buffer recovery
* Recovery journaling
* Unsaved-state preservation

---

# Tier 4 — Optional Features Compatible with the Philosophy

## Minimal Markdown Preview

* Lightweight preview mode
* No WYSIWYG editor
* No split-pane dependency

## Task Awareness

* Checkbox detection
* Task-focused searches
* Incomplete-task filtering

## Saved Searches

* Persistent search filters
* Smart views without folders

## CLI Integration

* Terminal capture
* Scriptable search/open
* External workflow integration

## Encryption-at-Rest

* Optional encrypted storage
* Sync-compatible design

---

# Features Likely to Harm the Product

## Organizational Complexity

* Deep folder hierarchies
* Mandatory notebooks
* Heavy taxonomy systems

## Rich Text / WYSIWYG

* Rich formatting editors
* Proprietary document models

## Plugin Ecosystems

* Startup slowdown
* Workflow fragmentation
* Reliability degradation

## Database-Only Storage

* Hidden proprietary state
* Reduced portability
* Reduced inspectability

## Heavy PKM Features

* Graph views
* Wiki-link obsession
* Complex backlink systems

## Excessive Metadata

* Mandatory frontmatter
* Structured schemas
* Metadata-first workflows

