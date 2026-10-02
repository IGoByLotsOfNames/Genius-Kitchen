# Genius Kitchen: the project story

[← Back to the application](../README.md)

## Why I built it

Food in my household was sometimes discovered only after it had expired. At the same time, deciding what to cook could be difficult even when ingredients were already available. I wanted a desktop application that made those ingredients visible and connected them to meal ideas.

I developed Genius Kitchen as a personal project during 2021–2023. I worked on the application logic, object-oriented Python structure, Tkinter interface, local data handling, recipe retrieval and Windows distribution. The project received a Distinction Award and the sole People's Choice Award at the 2021 Coding Lab International Coding Competition.

## The original application

The historical Windows application combined:

- **An ingredient inventory:** category views, quantities and expiry information.
- **Recipe discovery:** ingredient keywords used to retrieve recipe suggestions and links from the web.
- **Multiple interface languages:** English, Thai, Chinese and an experimental Pirate Lingo option. The Chinese translation included a collaborator's contribution.
- **Distribution and updates:** downloadable Windows builds and update metadata retrieved through a Discord-based channel, avoiding a paid dedicated server.

The original recipe suggestions were keyword-based. They did not establish that an entire recipe could be cooked using the exact quantities in the inventory. The aim was to help reduce forgotten food; no measured reduction in household waste or user-adoption figure is claimed here.

<img src="visuals/original-logo.png" alt="Original Genius Kitchen logo from the project archive" width="150">

*Original project logo, preserved from the source archive.*

## What the public repository contains

The current Python package reconstructs the central product behaviour in a smaller, inspectable form. It is not a byte-for-byte publication of the historical application or the source of every historical executable.

| Area | Original Windows application | Current public implementation |
| --- | --- | --- |
| Interface | Larger Tkinter application with category screens and settings | Inventory and Recipe matches tabs |
| Inventory | Quantities, categories and expiry views | Typed ingredient objects, expiry ordering and date filters |
| Suggestions | Network retrieval using ingredient keywords | Deterministic ingredient-name matching against six local recipes |
| Persistence | Historical local application data | JSON with a temporary-file replacement step |
| Languages | Multiple interface languages | English interface |
| Updates | Remote metadata and distributed Windows builds | Run the checked-out Python package locally |
| Tests | Original archive preserved separately | Five focused unit tests for inventory and matching behaviour |

The historical network integrations, private configuration and recipe-image archive are not included in this implementation. The original recorded demonstration also shows the historical interface, so it should not be treated as a screenshot of the current package.

## Design choices visible in today's code

### Separate the rules from the window

[`Inventory`](../src/genius_kitchen/inventory.py) and the [recipe matcher](../src/genius_kitchen/recipes.py) can run without Tkinter. That makes expiry boundaries and ranking behaviour easier to inspect and test than when all operations live in a GUI callback.

### Keep a match understandable

The matching score is a simple fraction of ingredient names present. Users can see the missing names rather than receiving an opaque recommendation. It is intentionally limited: ingredient aliases, nutritional suitability and required quantities are not modelled.

### Keep the current demonstration local

The bundled recipe data removes a live website dependency from the basic workflow. This trades breadth for a reproducible example. The JSON store writes a temporary file before replacing the inventory file; it is not a database transaction system, multi-user store or full backup strategy.

### Preserve the history without conflating versions

The original project demonstrates the breadth of a self-directed product build. The current package provides a compact view of its central domain rules. Distinguishing the two makes it possible to discuss both the product decisions and the implementation accurately.

## Reading the code

Start with [`models.py`](../src/genius_kitchen/models.py), follow the filtering in [`inventory.py`](../src/genius_kitchen/inventory.py), then inspect [`recipes.py`](../src/genius_kitchen/recipes.py). [`app.py`](../src/genius_kitchen/app.py) connects those components to the desktop interface.

The [architecture and matching diagrams](../README.md#how-the-current-code-fits-together) are schematics of the current code. Their editable generator is in [`visuals/render_diagrams.py`](visuals/render_diagrams.py).
