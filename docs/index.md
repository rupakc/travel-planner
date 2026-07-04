---
title: Travel Planner
description: AI-powered trip planning — flights, hotels, activities, visa, packing lists, emergency contacts and more, all in one place.
---

# Travel Planner

**Plan your entire trip in one go — no tab-switching, no guesswork.**

[Open the App](https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app){: .btn} &nbsp; [GitHub](https://github.com/rupakc/travel-planner){: .btn}

---

## What is Travel Planner?

Travel Planner is an app that takes the hard work out of trip planning. You enter your destination, travel dates, budget, and what you enjoy doing — and a team of AI specialists immediately gets to work on your behalf.

Within 30 seconds you have:

- flight options and price guidance
- hotels broken down by neighbourhood and budget level
- activities ranked by how well they match your interests
- must-see landmarks and places with ratings and links
- visa entry requirements for your passport
- local emergency numbers, your country's embassy, and survival phrases
- SIM card and eSIM options
- currency and money tips
- local transport advice
- a packing list tailored to your destination and weather
- a full day-by-day itinerary

Everything appears on screen as it's ready — you don't wait for a single slow loading screen.

---

## Features at a glance

### Plan your trip

**Flights**
Typical airlines, route options, rough price ranges, and advice on when to book — whether to grab a deal now or hold off for a better price.

**Hotels**
The best neighbourhoods to stay in (explained by what makes each one good for your type of trip), accommodation options from budget hostels to boutique hotels, and approximate prices per night.

**Activities**
A list of things to do, automatically sorted so the activities that match your stated interests appear first. A food lover planning a Tokyo trip sees izakayas and ramen tours near the top, not the standard tourist checklist.

**Places to See**
Landmark highlights — temples, museums, viewpoints, markets — with visitor ratings, how long to allow, and links to read more. Sourced from live Google data and summarised by AI.

**Day-by-day Itinerary**
A logical schedule that fits your activities into mornings, afternoons, and evenings, keeps walking distances sensible, and links to your chosen accommodation area. View it as a timeline grid or read it as a day-by-day list, with weather shown for each day.

---

### Know before you go

**Visa Requirements**
Entry rules specific to your passport nationality: whether you need a visa, how to apply, what documents to bring, processing times, and fees.

**Safety & Emergency Card**
The information you hope you never need but are glad to have. Local emergency numbers (police, ambulance, fire, tourist police), your nearest international hospital, your country's embassy address and after-hours phone number, 10 phonetic survival phrases in the local language, and local laws that travellers sometimes accidentally break. Printable as a clean card.

**Travel Confidence Score**
An instant snapshot of how straightforward the trip is — scored across five dimensions: visa ease, safety, how widely English is spoken, tourist infrastructure quality, and whether your budget is realistic for the destination. Green means easy, amber means plan ahead, red means do your homework.

**Travel Tips**
Cultural etiquette (what's polite, what's rude), safety advice, health precautions, tipping norms, dress codes for religious sites, and practical local knowledge you won't find on the booking site.

**Weather**
Day-by-day forecast for your exact travel dates (Open-Meteo for trips within 16 days, seasonal climate estimates beyond) — on multi-city trips, each stop is forecast only for the days you're actually there, grouped under a city header.

---

### Travel smart

**SIM Cards & eSIMs**
Which local carrier to use, typical data plan options and prices, whether an eSIM works for your phone, and where to buy one (airport, convenience store, carrier shop).

**Currency & Money**
The local currency, rough exchange rates, whether to exchange before you travel or at the destination, ATM availability and fees, how widely cards are accepted, and digital payment culture.

**Getting Around**
Airport transfer options with price ranges, how to use the local public transport, ride-hailing app availability, taxi culture, and intercity travel if you're visiting multiple cities.

**Layover Optimizer**
Long layover on the way? Get a "make the most of it" mini-plan — whether you can leave the airport, transit visa notes, and a realistic timed excursion.

**Itinerary Health Check**
An adversarial AI review of the finished plan — it hunts for pacing problems, timing clashes, visa deadlines you'd miss, weather conflicts with outdoor days, and budget overruns, and reports them with severity levels.

**Flight Price Advisor**
Based on historical pricing patterns for your specific route, this tells you whether current prices are above or below average, recommends whether to book now or wait, and shows a chart of how prices typically move in the weeks before departure.

**Smart Packing List**
A personalised checklist built from your destination, travel dates, planned activities, and weather forecast. Items are grouped by category (documents, clothing, electronics, medications, activity gear) with essentials flagged. Tick off items as you pack and add your own — saved automatically to your plan.

---

### Multi-city journeys

**Multiple stops, one search**
Enter an ordered list of stops (Paris → Rome → Barcelona) and every section covers every city, each item tagged with a 📍 city chip. Days are split across cities automatically, flights are searched **per leg** (including the transatlantic bookends) with one pick per leg and a running total, and the itinerary visits your cities in exactly the order you entered them. See [Multi-City Trips](Multi-City-Trips.md).

---

### Personalised to you

**Taste Graph**
The app learns your travel style from what you actually select — non-stop flights, boutique hotels, food-first activities — and quietly ranks matching options higher on every future search. No forms; it's mined from your saved plans. See [Personalization](Personalization.md).

**Serendipity dial & pace**
Slide between famous classics and hidden local gems; choose a relaxed, balanced, or packed daily pace.

---

### Discover where to go

**Surprise Me**
Not sure where to go? Enter your origin, budget, travel dates, and interests, and get five curated destination suggestions. Each card shows estimated trip cost, typical weather for your dates, visa status for your passport, approximate flight time, and the specific reasons this destination suits your interests. Click "Plan this trip" to immediately start planning with that destination pre-filled.

---

### Save and organise

**My Plan**
A drawer that follows you through the app. Select the exact flights, hotel, activities, and other items you want. See a live cost total as you build. Name your plan ("The Rainy Tokyo Adventure"), save it, and reload it whenever you come back.

**Chat**
A conversational AI travel advisor. Questions are answered instantly from the model's own expertise; describe a trip and the full planning pipeline streams structured results into the conversation, asks targeted clarifying questions when something's missing, and re-runs only the affected sections when you say "make it cheaper". See [Chat Assistant](Chat-Assistant.md).

**Shareable trip card**
Every saved plan gets a public share page with the complete trip — flights per leg, hotel, full itinerary with your notes, and all picks — downloadable as a single full-page PNG. See [Plans & Sharing](Sharing-and-Plans.md).

---

## How it works

The app uses a team of 15 specialist AI agents. When you search, they all run at the same time. As each one finishes, its results appear on your screen immediately — so you see flights within a few seconds, then hotels, then activities, and so on. You're never waiting for everything to load at once.

Some results (like visa rules and emergency numbers) come from carefully maintained lookup tables and appear instantly, before any AI call has even finished. The AI agents then enhance these with more detail.

Once activities and hotels are ready, a final agent synthesises everything into your day-by-day itinerary.

---

## Tech stack (for the curious)

| Layer | Technology |
|---|---|
| AI | Anthropic Claude, 15 specialist agents |
| Backend | Python, FastAPI |
| Frontend | React, Tailwind CSS |
| Infrastructure | Google Cloud Run, Terraform, GitHub Actions |

---

## Links

- [GitHub repository](https://github.com/rupakc/travel-planner) — source code and issue tracker
- [API documentation](https://travel-planner-backend-2hrxgxqboa-ew.a.run.app/docs) — interactive REST API explorer
- [Setup guide](https://github.com/rupakc/travel-planner/blob/main/docs/Setup-and-Installation.md) — run the app locally
- [Report a bug](https://github.com/rupakc/travel-planner/issues) — open an issue on GitHub

---

*Built with [Anthropic Claude](https://anthropic.com). MIT licence.*
