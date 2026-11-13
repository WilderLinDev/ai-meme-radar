# 3. Trend, Format and Template opportunity are the research entities

Status: accepted (2026-11-13, rebuild)

The previous design made one "meme" the only unit, discovered mostly from Creative Center Top 100 and scored 0-100. That missed trends that are not memes (effects, transformations, photo-to-video), merged the trend with what we would build, and hid trade-offs in a sum.

Now: a **trend** spreads, a **format** is the reusable pattern behind it, a **template opportunity** is what we could ship. Relations are many-to-many link events. Keywords and sites are first-class link targets so social, search, product and market evidence connect. Creative Center is one social source among many.

Entity ids are permanent kebab-case slugs; names and aliases are dedupe keys, and ingest rejects a new entity that collides with an existing one.
