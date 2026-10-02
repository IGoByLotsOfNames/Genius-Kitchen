# Genius Kitchen: a project I keep returning to

[← Back to the application](../README.md)

## The problem was at home

Food in my household was sometimes discovered only after it had expired. On other evenings, deciding what to cook was difficult even when ingredients were already available. I wanted to connect those two problems: make the pantry easier to see, then suggest something useful to do with it.

That became Genius Kitchen, a personal Windows application I developed during 2021–2023. The original project received a **Distinction Award and the sole People's Choice Award at the 2021 Coding Lab International Coding Competition**.

<img src="visuals/original-logo.png" alt="Original Genius Kitchen logo" width="150">

*The original logo, retained as the project evolved.*

## Building the first application

I used **Python, Tkinter and object-oriented programming** to organize the interface and application logic. The early application tracked ingredient categories, quantities and expiry dates, using the computer's date to identify items that needed attention.

I also wanted the inventory to lead somewhere useful. I experimented with `requests` to retrieve recipe information from the web and present suggestions related to ingredients already at home. That work involved learning through trial and error: parsing responses, connecting recipe information to the interface, and handling the practical details around a desktop application.

The original recipe discovery used ingredient keywords. It suggested ideas rather than proving that a household had the exact quantities needed to cook every recipe.

### Getting it onto another computer

I published downloadable Windows builds and worked out how to distribute updates without paying for a dedicated server. The application retrieved version information through a Discord-based channel, which let the update mechanism use an existing service.

The original interface also supported English, Thai and Chinese, along with an experimental Pirate Lingo option. The Chinese translation included a collaborator's contribution.

Those features reflect the original project's priorities: making something people could open, use and update on their own Windows computers. The historical archive includes several versions and an early recorded demonstration; it is preserved separately from the current implementation.

## Returning to it with Codex

In 2026, I returned to Genius Kitchen with the same underlying product idea and a different development process. The existing GitHub implementation became the working base for an **AI-assisted reconstruction and modernisation**.

I set the direction for the project and worked with **Codex, which contributed substantially to implementation, debugging, testing, documentation and packaging**. This was a significant development collaboration. The resulting implementation and supporting engineering work should be understood in that context.

The work went beyond changing the appearance of the repository. It tightened validation, improved persistence behavior, separated application rules from interface code, addressed duplicate-item and date-boundary behavior, and added automated tests and reproducible benchmarks. It also produced portable Windows builds and a responsive local browser interface.

The project now has two complementary forms: a native Tkinter application and a browser interface backed by a local Python process. AI was part of building and improving them. Their recipe logic remains deterministic and runs on the user's computer.

## What changed, and what stayed

| Area | Early Windows application | Current desktop and browser editions |
| --- | --- | --- |
| Purpose | Make ingredients visible and connect them to meal ideas | The same household workflow, with more explicit rules and evidence |
| Interface | Larger Tkinter application with category screens and settings | Native Tkinter interface plus a responsive local browser interface |
| Inventory | Categories, quantities and expiry views | Validated records, expiry-aware matching and tested persistence behavior |
| Recipe discovery | Network retrieval using ingredient keywords | Deterministic ingredient-name coverage against six bundled examples |
| Browser workflow | No equivalent current browser edition | Editing, search, expiry filters, recipe instructions, JSON backup/import |
| Languages | Multiple interface languages | English interface |
| Distribution | Downloadable Windows builds and Discord-based update metadata | Portable Windows packaging, demo launchers and build/verification scripts |
| Updates and synchronization | Historical remote update mechanism | No automatic update service; desktop and browser pantry files remain separate |
| Engineering evidence | Historical code and recorded demonstration | Automated tests, injected failures, dated benchmarks and packaged-app checks |

This is a continuous personal project whose implementation has changed over time. The current code does not reproduce every historical feature or every old executable. Keeping those differences explicit makes it possible to understand the original choices and the later work without losing either part of the story.

## Some decisions that made the newer version stronger

### Save first, then show the edit

An inventory application should not display a successful change that failed to reach storage. The desktop stages a candidate inventory, saves it, and only then adopts it and refreshes the views. Tests inject failures and check the inventory, saved bytes, table and form state afterward.

The JSON store serializes to a sibling temporary file before replacing the destination. That gives a small local application a clear failure boundary. It still assumes one process per inventory file; locking, cross-process conflict resolution and power-loss recovery need further work.

### Treat equal-looking items as separate items

Two rows can have the same name, or even the same visible fields. The selected occurrence still needs to be the one removed. Tests cover these cases and make the distinction between a row's identity and its values explicit.

### Give time-dependent behavior a controllable clock

Expiry labels and recipe availability use the same reference date during a refresh. A supplied date function makes midnight and backward-clock cases repeatable in tests. That is more dependable than waiting for a real date change or scattering calls to the system clock through the interface.

### Keep a recipe match understandable

The matcher reports which names are present and which are missing. Coverage is the fraction of recipe ingredient entries matched by the available-name set. This keeps the result easy to follow, while leaving room for better ingredient modelling later.

Six illustrative recipes provide a reproducible starting point. Required quantities, unit conversions, aliases, allergies and nutrition are outside the current matcher. A future catalog should have clear provenance and an explicit definition of what “can cook this” means.

### Check the artifact people will actually run

Source tests are one layer. The packaging work also checks actual frozen executables: bundled resources, core module identity, HTTP behavior, application shutdown and desktop Add/Remove behavior. Dated manifests record file hashes so a built artifact can be compared with the one that was verified.

The [validation guide](VERIFICATION.md) separates desktop tests, backend tests, frontend logic tests and packaged-app checks. It also explains the boundaries of the available evidence.

## What the work taught me

The original project gave me experience turning a household frustration into a working desktop product and finding practical ways to distribute it. Revisiting it brought the less visible parts of software into focus: exact data rules, failure behavior, packaging, testability and a clear account of what has actually been checked.

The AI-assisted phase is part of that development story. It let me pursue a broader reconstruction and stronger engineering checks, while making attribution and verification especially important. The project is most useful when its code, history and evidence tell the same story.

The next questions are practical: how people would use it over time, which ingredients and recipes matter to them, and which improvements would make it worth returning to. No user-adoption figure or measured reduction in food waste is established here.

## Explore the current work

- [README and current screenshots](../README.md)
- [Desktop demo](DEMO.txt) and [local browser instructions](../web/RUN_ME.txt)
- [Domain records](../src/genius_kitchen/models.py), [inventory](../src/genius_kitchen/inventory.py) and [recipe matcher](../src/genius_kitchen/recipes.py)
- [Checks and measurements](VERIFICATION.md), [testing instructions](TESTING.txt) and [benchmark method](BENCHMARKING.txt)

The original name, logo and ownership remain with the author under the repository's [existing licence](../LICENSE).
