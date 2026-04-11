# Developer Experience & Pipeline Improvements

## Single deploy command

Replace the two-step `cdk deploy` + `./scripts/setup-env.sh` flow with a single unified command
that handles both infrastructure deployment and environment setup in one shot.

## Encounter asset caching

Cache encounter backgrounds so they are not regenerated on every request.
Examples of cacheable assets: sad king, Prince of Persia backgrounds.

## Animator + Drawing in parallel

Run the Animator and Drawing pipeline steps concurrently instead of sequentially
to reduce overall episode generation time.

## Rename "Obstacles" to "Encounters"

Rename the concept throughout the codebase and docs — better reflects the narrative role
these elements play in the story.
