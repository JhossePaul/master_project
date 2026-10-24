"""voc-nlp: lógica pura de inferencia y monitoreo de BBVA VoC Analyzer.

Porta de ``voc_analytics`` (los experimentos de ``experiments/analytics``)
los criterios que se decidieron ahí, sin cambiarlos. Los módulos con
dependencias pesadas viven en *extras*: ``sentiment_model`` y ``explain``
(``[sentiment]``), ``aspects`` y ``sentiment_gemini`` (``[gemini]``) y
``topics`` (``[topics]``).
"""
