# experiments/project_viability

EDA preliminar de viabilidad del proyecto, previo al motor de ingesta y a
EPIC-5. `Extracción_reviews.ipynb` (Colab) descarga una muestra de reseñas
de BBVA México con `google-play-scraper`, la limpia y compara las estrellas
con el sentimiento de RoBERTuito (`pysentimiento`) y con la polaridad léxica
de `TextBlob`.

Ese léxico es la referencia **T0** de la competencia de modelos (5.4):
`voc_analytics.sentiment.models.pretrained` lo reproduce sobre el oro, con el
protocolo común.

El cuaderno se versiona **sin salidas**: las originales incluían texto de
reseñas, que nunca entra a git. No es parte del proyecto `uv` de
`experiments/analytics` (usa `pandas`, `seaborn` y `google-play-scraper`).
