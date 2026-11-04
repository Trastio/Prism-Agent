# 工具覆盖矩阵 · v1_1

- 轨迹源: `eval\trajectories\eval-trajectories.jsonl`
- 生成时间: 2026-10-14 11:12
- 覆盖工具: 30/33（全集=extension KNOWN_BUSINESS_TOOLS+web/social/utility）

## 题 × 工具调用计数

| 题 | set | 工具调用（×次数） | 合计 |
|---|---|---|---|
| (unmatched) | ? | query_sales×5、submit_conclusion×4、resolve_series×3 | 12 |
| config-03 | frozen | submit_conclusion×14、search_reviews×9、social_search×6、resolve_series×5、query_config×5、get_trims×5、get_config_detail×5、web_search×3、fetch_content×2、get_search_content×2、get_review_analysis×1、get_dimension_reviews×1、compare_configs_valued×1、social_post_comments×1、sentiment_dimension×1 | 61 |
| config-04 | frozen | get_config_detail×11、submit_conclusion×11、compare_configs_valued×4、resolve_series×3、query_config×3、web_search×3、social_search×2、get_trims×1、fetch_content×1、search_reviews×1 | 40 |
| config-05 | frozen | submit_conclusion×14、resolve_series×4、get_trims×4、compare_configs_valued×4、load_skill×2、get_config_detail×1 | 29 |
| config-06 | dev | submit_conclusion×11、resolve_series×7、search_cars×5、get_trims×5、compare_configs_valued×4、query_config×3、query_sales×3、query_reviews×3、get_sales_detail×1、sentiment_overview×1、get_dimension_reviews×1、get_config_detail×1、search_reviews×1 | 46 |
| config-07 | dev | resolve_series×35、get_trims×14、submit_conclusion×7、compare_configs_valued×6、search_cars×4、ask_user_question×2、score_models×2 | 70 |
| config-08 | dev | submit_conclusion×8、compare_configs_valued×3、resolve_series×2、query_config×2、get_trims×2、get_config_detail×1 | 18 |
| config-09 | frozen | resolve_series×4、get_trims×4、submit_conclusion×4、compare_configs_valued×3、load_skill×2、get_config_detail×2、ask_user_question×1 | 20 |
| config-10 | frozen | resolve_series×12、query_config×12、submit_conclusion×12、social_search×12、search_cars×8、get_trims×6、query_sales×5、query_reviews×4、ask_user_question×4、social_post_comments×4、sentiment_overview×2、web_search×2、get_sales_detail×1 | 84 |
| config-11 | dev | resolve_series×22、query_config×18、get_trims×13、get_config_detail×8、social_search×6、submit_conclusion×5、search_cars×3、load_skill×1、compare_configs_valued×1 | 77 |
| config-12 | frozen | resolve_series×14、get_trims×8、compare_configs_valued×5、submit_conclusion×5、load_skill×2、search_cars×2、web_search×1、get_config_detail×1、ask_user_question×1、fetch_content×1、score_models×1 | 41 |
| config-13 | frozen | submit_conclusion×9、resolve_series×2、query_config×2、get_trims×2、search_cars×2、compare_configs_valued×2、get_config_detail×2、query_sales×2、get_sales_detail×2 | 25 |
| cross-01 | dev | submit_conclusion×23、query_reviews×3、search_reviews×3、resolve_series×2、query_config×2、query_sales×2、get_dimension_reviews×2、get_model_detail×1、sentiment_dimension×1、get_config_detail×1 | 40 |
| cross-02 | dev | submit_conclusion×13、query_sales×8、resolve_series×2、get_sales_detail×1、get_trims×1 | 25 |
| cross-03 | dev | submit_conclusion×5、resolve_series×2、query_config×2、get_trims×2、get_config_detail×1 | 12 |
| cross-04 | dev | submit_conclusion×7、query_reviews×4、resolve_series×2、get_review_analysis×2、get_model_detail×2、get_dimension_reviews×1 | 18 |
| cross-05 | dev | submit_conclusion×33、query_sales×12、resolve_series×2、search_cars×2、get_sales_detail×2、query_config×2、sentiment_events×2、sentiment_overview×2、query_reviews×2、sentiment_dimension×2、social_search×2、sentiment_trend×1、sentiment_competitive×1、get_dimension_reviews×1、sentiment_posts×1 | 67 |
| cross-06 | dev | submit_conclusion×17、query_sales×3、resolve_series×2、search_cars×2、query_reviews×2、get_dimension_reviews×2、sentiment_overview×2、sentiment_events×2、sentiment_dimension×1、sentiment_trend×1 | 34 |
| cross-07 | dev | query_sales×13、search_cars×5、resolve_series×4、get_sales_detail×3、submit_conclusion×2、sentiment_overview×1、sentiment_events×1、get_trims×1 | 30 |
| cross-08 | dev | submit_conclusion×7、resolve_series×6、social_search×6、sentiment_overview×4、search_cars×3、query_sales×3、get_sales_detail×3、ask_user_question×2、query_config×2、query_reviews×1、sentiment_dimension×1、sentiment_trend×1、sentiment_events×1 | 40 |
| cross-09 | dev | submit_conclusion×20、search_cars×19、query_sales×10、resolve_series×9、social_search×5、query_config×4、get_sales_detail×4、get_trims×3、web_search×2、get_model_detail×1 | 77 |
| cross-10 | dev | social_search×6、resolve_series×5、sentiment_events×5、query_sales×5、submit_conclusion×4、sentiment_overview×3、search_cars×2、get_sales_detail×1、query_reviews×1 | 32 |
| reviews-03 | dev | resolve_series×11、submit_conclusion×7、query_reviews×6、get_dimension_reviews×3、search_cars×2、get_model_detail×2、get_review_analysis×2、get_trims×1、search_reviews×1 | 35 |
| reviews-04 | dev | submit_conclusion×12、resolve_series×4、get_review_analysis×3、query_sales×3、get_trims×2、query_reviews×2、get_sales_detail×2、search_cars×1、search_reviews×1、get_model_detail×1 | 31 |
| reviews-05 | frozen | submit_conclusion×7、get_dimension_reviews×4、resolve_series×2、query_reviews×2、search_reviews×2 | 17 |
| reviews-06 | frozen | submit_conclusion×7、resolve_series×6、query_reviews×4、search_cars×2、ask_user_question×2、get_similar_models×2 | 23 |
| reviews-07 | frozen | submit_conclusion×7、query_reviews×6、social_search×6、resolve_series×4、search_cars×3、sentiment_overview×3、query_sales×2、get_sales_detail×2、social_post_comments×2、sentiment_dimension×1、sentiment_events×1、load_skill×1 | 38 |
| reviews-08 | frozen | resolve_series×10、query_reviews×9、submit_conclusion×8、get_dimension_reviews×4、search_reviews×4、get_model_detail×4、search_cars×1 | 40 |
| reviews-09 | dev | submit_conclusion×7、search_reviews×6、resolve_series×4、search_cars×4、query_reviews×4、get_dimension_reviews×4、get_review_analysis×2、get_similar_models×1 | 32 |
| reviews-10 | dev | resolve_series×40、query_reviews×36、submit_conclusion×9、get_review_analysis×8、search_cars×3、get_similar_models×1 | 97 |
| reviews-11 | dev | resolve_series×38、query_reviews×31、social_search×14、submit_conclusion×5、search_cars×3、sentiment_overview×3、get_sales_detail×2、ask_user_question×2、load_skill×2、social_post_comments×2、get_trims×1 | 103 |
| sales-03 | frozen | submit_conclusion×6、query_sales×3、resolve_series×2、get_trims×2、get_sales_detail×1 | 14 |
| sales-04 | frozen | query_sales×5、submit_conclusion×4、resolve_series×2、get_sales_detail×2 | 13 |
| sales-05 | dev | query_sales×4、submit_conclusion×4、resolve_series×2、query_config×2 | 12 |
| sales-06 | dev | submit_conclusion×19、resolve_series×7、search_cars×4、get_trims×3、get_sales_detail×3、query_sales×3、query_config×2、ask_user_question×1 | 42 |
| sales-07 | frozen | query_sales×3、resolve_series×2、submit_conclusion×2 | 7 |
| sales-08 | dev | search_cars×4、query_sales×4、resolve_series×3、submit_conclusion×3 | 14 |
| sales-09 | dev | query_sales×6、search_cars×4、resolve_series×3、get_sales_detail×2、submit_conclusion×2 | 17 |
| sales-10 | dev | query_sales×12、submit_conclusion×6、resolve_series×6、search_cars×3 | 27 |
| sales-11 | frozen | query_sales×6、submit_conclusion×4、get_sales_detail×3、resolve_series×2 | 15 |
| sales-12 | frozen | query_sales×8、submit_conclusion×8、resolve_series×7、get_sales_detail×2 | 25 |
| sales-13 | frozen | query_sales×8、resolve_series×6、get_sales_detail×5、submit_conclusion×3、search_cars×2 | 24 |
| sales-14 | frozen | query_sales×9、resolve_series×8、submit_conclusion×6、get_sales_detail×4、search_cars×2 | 29 |
| sentiment-03 | dev | submit_conclusion×10、resolve_series×2、sentiment_overview×2、sentiment_trend×2、sentiment_dimension×2、sentiment_events×2、sentiment_posts×2、sentiment_competitive×1 | 23 |
| sentiment-04 | dev | submit_conclusion×6、get_dimension_reviews×4、search_reviews×4、resolve_series×2、query_reviews×2、sentiment_dimension×1、sentiment_events×1 | 20 |
| sentiment-05 | dev | social_search×14、resolve_series×6、social_post_comments×6、search_cars×4、submit_conclusion×4、sentiment_overview×3、query_sales×3、query_reviews×2、query_config×2、sentiment_trend×1、sentiment_dimension×1、sentiment_posts×1、sentiment_events×1、get_sales_detail×1、load_skill×1 | 50 |
| sentiment-06 | dev | social_search×13、submit_conclusion×6、sentiment_dimension×4、sentiment_posts×3、resolve_series×2、sentiment_events×2、sentiment_overview×2、sentiment_trend×2 | 34 |
| sentiment-07 | dev | submit_conclusion×8、query_reviews×6、get_dimension_reviews×4、resolve_series×2、sentiment_overview×2、sentiment_dimension×2、sentiment_events×2、sentiment_posts×2、get_model_detail×1、query_sales×1 | 30 |
| sentiment-08 | frozen | social_search×17、sentiment_overview×8、resolve_series×4、search_cars×3、submit_conclusion×3、social_post_comments×3、ask_user_question×2、sentiment_competitive×2、sentiment_trend×1、sentiment_events×1、sentiment_dimension×1、sentiment_posts×1、get_sales_detail×1 | 47 |
| social-01 | dev | social_post_comments×5、social_search×3、fetch_content×2、resolve_series×1 | 11 |
| social-02 | dev | social_user_profile×2 | 2 |
| trap-01 | dev | submit_conclusion×4、resolve_series×2、query_config×2、get_trims×2、get_config_detail×1 | 11 |
| trap-02 | dev | query_sales×3、submit_conclusion×3、resolve_series×2、get_sales_detail×2 | 10 |
| trap-03 | dev | submit_conclusion×17、query_sales×3、query_reviews×3、resolve_series×2、get_dimension_reviews×2、get_sales_detail×1、query_config×1 | 29 |
| trap-04 | dev | resolve_series×3、search_cars×2、query_sales×2、submit_conclusion×2、ask_user_question×1 | 10 |
| trap-05 | dev | submit_conclusion×8、query_reviews×3、get_dimension_reviews×3、resolve_series×2 | 16 |
| trap-06 | dev | resolve_series×3、search_cars×2、submit_conclusion×2、get_sales_detail×2、query_sales×1 | 10 |
| trap-07 | dev | submit_conclusion×6、get_config_detail×4、resolve_series×2、get_trims×2 | 14 |
| trap-08 | dev | resolve_series×14、get_trims×9、get_config_detail×7、compare_configs_valued×6、submit_conclusion×4、search_cars×2、query_config×1 | 43 |
| trap-09 | dev | resolve_series×2、query_sales×2、submit_conclusion×2 | 6 |
| trap-10 | dev | （零调用） | 0 |

## 工具覆盖汇总

| 工具 | 调用总数 |
|---|---|
| submit_conclusion | 456 |
| resolve_series | 369 |
| query_sales | 162 |
| query_reviews | 136 |
| social_search | 112 |
| search_cars | 108 |
| get_trims | 93 |
| query_config | 67 |
| get_sales_detail | 53 |
| get_config_detail | 46 |
| compare_configs_valued | 39 |
| sentiment_overview | 38 |
| get_dimension_reviews | 36 |
| search_reviews | 32 |
| social_post_comments | 23 |
| sentiment_events | 21 |
| get_review_analysis | 18 |
| sentiment_dimension | 18 |
| ask_user_question | 18 |
| get_model_detail | 12 |
| web_search | 11 |
| load_skill | 11 |
| sentiment_posts | 10 |
| sentiment_trend | 9 |
| fetch_content | 6 |
| get_similar_models | 4 |
| sentiment_competitive | 4 |
| score_models | 3 |
| get_search_content | 2 |
| social_user_profile | 2 |

## 零覆盖工具清单

- **business**（0/22 未覆盖）: —
- **web**（1/4 未覆盖）: source_check
- **social**（1/4 未覆盖）: social_user_posts
- **utility**（1/3 未覆盖）: export_document
