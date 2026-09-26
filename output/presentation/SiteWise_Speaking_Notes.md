# SiteWise UK: 1 minute 50 second introduction

Advance at the times below, then switch to the website. Sources are in the PowerPoint speaker notes.

## Slide 1: The problem (0:00–0:25)

SiteWise UK helps people understand planning considerations before committing to a property. The idea came from my family looking at a development site. We discovered that a protected tree complicated the building layout. For buyers unfamiliar with the UK planning process, important information is scattered across council documents, maps and previous applications. We wanted to bring those checks forward.

## Slide 2: The solution (0:25–0:45)

You choose a location and describe your proposal. SiteWise retrieves council guidance, checks available spatial layers and searches nearby or similar applications. The dashboard explains what needs investigation and links back to the evidence. An optional AI summary explains those results, while missing information stays explicitly unknown.

## Slide 3: The data (0:45–1:10)

We combine the supplied London planning dataset with public GLA spatial layers and the Planning Data API. Official council webpages and PDFs add the actual guidance relevant to a proposal. That distinction matters: a map designation alone does not explain the rule. Our council-text pilot currently covers Wandsworth, Westminster and Lambeth, plus selected London-wide policies.

## Slide 4: Legacy project credits (1:10–1:35)

We built on the comparable-application approach from 0-the-spike, adapting TF-IDF and cosine similarity to our CSV. ConfidentPlanner informed spatial and nearby searches, while 0-RIBS informed validation and caching. We independently implemented concepts where licensing restricted copying. We did not import their approval models, and a similarity score never represents an approval probability.

## Slide 5: Demo handover (1:35–1:50)

Let me show you a proposal for a rear extension and two new homes. I will select a location, review the council guidance and show which issues still need checking. This is preliminary screening to support a better planning conversation.
