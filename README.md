# Weather App

A single static page with one merged, locally AI-corrected weather forecast for
Brda, Slovenia — blended from multiple open forecast models, verified against
regional station observations, with ARSO nowcast imagery (radar, satellite,
hail). No backend: a GitHub Actions pipeline fetches data, applies an ML
correction, and commits JSON that the page renders via GitHub Pages.

Status: early scaffold — nothing to see yet.
