-- schema.sql · 取代性实验 B 系列挑战者配套（生成物，勿手改）
-- 来源：eval/snapshots/snap-20261012-1222 两库 sqlite_master 只读导出
-- 生成方式：python sqlite3 只读连接 SELECT sql FROM sqlite_master（快照冻结，与判分同快照哈希）
-- 用途：随 SKILL.md 附给挑战者 agent（read_file("schema.sql")）——对挑战者从宽给全库结构，结论保守
-- 注意：月度列 month 为文本形如 '8月末'/'9月中'；零售滞后月 retail 可为 NULL（月中批=价格快照）

-- ======================================================================
-- 库：eval/snapshots/snap-20261012-1222/autohome.db  ·  autohome（主库：销量/口碑/配置/车系）  ·  9 tables
-- ======================================================================

CREATE TABLE config_snapshots (
	series_id VARCHAR NOT NULL, 
	series_name VARCHAR, 
	maker VARCHAR, 
	energy VARCHAR, 
	level VARCHAR, 
	price_range VARCHAR, 
	categories JSON NOT NULL, 
	fetched_at VARCHAR, 
	version INTEGER NOT NULL, decode_hit_rate REAL, 
	PRIMARY KEY (series_id)
);

CREATE TABLE conversations (
	session_id VARCHAR NOT NULL, 
	user_id VARCHAR NOT NULL, 
	messages VARCHAR NOT NULL, 
	created_at DATETIME, 
	last_active_at DATETIME, 
	PRIMARY KEY (session_id)
);

CREATE TABLE insight_cache (
	filter_hash VARCHAR NOT NULL, 
	model_id VARCHAR NOT NULL, 
	filter_json JSON NOT NULL, 
	summary_markdown VARCHAR, 
	review_refs JSON, 
	n INTEGER NOT NULL, 
	created_at DATETIME, 
	llm_model VARCHAR, 
	baseline_reviews INTEGER NOT NULL, 
	baseline_tags INTEGER NOT NULL, 
	PRIMARY KEY (filter_hash)
);

CREATE TABLE owner_reviews (
	review_id VARCHAR NOT NULL, 
	owner_id VARCHAR, 
	model_full_name VARCHAR NOT NULL, 
	model_id VARCHAR NOT NULL, 
	purchase_date DATE, 
	best_review_text VARCHAR NOT NULL, 
	worst_review_text VARCHAR NOT NULL, 
	raw_json JSON, 
	fetched_at DATETIME, spec_name VARCHAR, spec_id VARCHAR, score REAL, dimensions TEXT, buy_price TEXT, fuel_consumption TEXT, mileage TEXT, city TEXT, use_purposes TEXT, dimension_reviews TEXT, post_date TEXT, exinfo JSON, best_full_text TEXT, worst_full_text TEXT, 
	PRIMARY KEY (review_id)
);

CREATE TABLE review_tags (
	id INTEGER NOT NULL, 
	review_id VARCHAR NOT NULL, 
	owner_id VARCHAR NOT NULL, 
	model_full_name VARCHAR NOT NULL, 
	model_id VARCHAR NOT NULL, 
	tag_name VARCHAR NOT NULL, 
	sentiment VARCHAR NOT NULL, 
	source_text VARCHAR, 
	confidence FLOAT NOT NULL, tag_category TEXT DEFAULT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(review_id) REFERENCES owner_reviews (review_id)
);

CREATE TABLE sales_trim (
	model_code VARCHAR NOT NULL, 
	year INTEGER NOT NULL, 
	month VARCHAR NOT NULL, 
	manufacturer VARCHAR, 
	brand VARCHAR, 
	series VARCHAR, 
	level VARCHAR, 
	body VARCHAR, 
	displacement VARCHAR, 
	gearbox VARCHAR, 
	energy_type VARCHAR, 
	seats INTEGER, 
	drive VARCHAR, 
	fuel VARCHAR, 
	origin VARCHAR, 
	ev_range INTEGER, 
	version VARCHAR, 
	pre_msrp FLOAT, 
	length_mm INTEGER, 
	wheelbase_mm INTEGER, 
	launch_date VARCHAR, 
	prod_status VARCHAR, 
	model_name VARCHAR, 
	msrp FLOAT, 
	tp FLOAT, 
	discount FLOAT, 
	mix FLOAT, 
	retail INTEGER, 
	is_main VARCHAR, 
	hi_lo VARCHAR, 
	PRIMARY KEY (model_code, year, month)
);

CREATE TABLE series_summaries (
	series_id VARCHAR NOT NULL, 
	series_name VARCHAR, 
	brand_name VARCHAR, 
	brand_id VARCHAR, 
	level_name VARCHAR, 
	level_id VARCHAR, 
	price_range VARCHAR, 
	min_price FLOAT, 
	max_price FLOAT, 
	average_score FLOAT, 
	dimension_scores JSON, 
	review_count INTEGER, 
	consumption VARCHAR, 
	spec_groups JSON, 
	updated_at DATETIME, pph INTEGER, cmp_scores TEXT, cmp_pph TEXT, onsell_review_count INTEGER, level_rank INTEGER, level_series_count INTEGER, powertype INTEGER, consumption_battery TEXT, 
	PRIMARY KEY (series_id)
);

CREATE TABLE task_records (
	task_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	progress VARCHAR, 
	error VARCHAR, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (task_id)
);

CREATE TABLE user_preferences (
	user_id VARCHAR NOT NULL, 
	budget_max INTEGER, 
	budget_min INTEGER, 
	segments JSON, 
	energy_types JSON, 
	brands JSON, 
	dimension_weights JSON, 
	updated_at DATETIME, 
	PRIMARY KEY (user_id)
);

CREATE INDEX idx_owner_reviews_model_post ON owner_reviews(model_id, post_date, fetched_at);
CREATE INDEX ix_insight_cache_model_id ON insight_cache (model_id);
CREATE INDEX ix_owner_reviews_model_id ON owner_reviews (model_id);
CREATE INDEX ix_owner_reviews_spec_id ON owner_reviews(spec_id);
CREATE INDEX ix_review_tags_model_id ON review_tags (model_id);
CREATE INDEX ix_review_tags_model_id_sentiment ON review_tags(model_id, sentiment);
CREATE INDEX ix_review_tags_review_id ON review_tags (review_id);
CREATE INDEX ix_review_tags_sentiment ON review_tags(sentiment);
CREATE INDEX ix_review_tags_tag_category ON review_tags(tag_category);
CREATE INDEX ix_sales_trim_series ON sales_trim (series);
CREATE UNIQUE INDEX uq_review_tags_rid_name_senti ON review_tags(review_id, tag_name, sentiment);
-- ======================================================================
-- 库：eval/snapshots/snap-20261012-1222/vehicle_sentiment.db  ·  vehicle_sentiment（舆情库：帖子/维度/事件/缺陷簇）  ·  17 tables
-- ======================================================================

CREATE TABLE analyzed_posts (
	id VARCHAR NOT NULL, 
	post_id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	sentiment VARCHAR NOT NULL, 
	event_tags TEXT, 
	opinion_tags TEXT, 
	confidence FLOAT, 
	analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	model_used VARCHAR, 
	dim_sentiment TEXT, 
	comment_summary TEXT, subject VARCHAR, subject_name VARCHAR DEFAULT '', 
	PRIMARY KEY (id)
);

CREATE TABLE anomaly_events (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	date DATE NOT NULL, 
	volume_change_rate FLOAT, 
	today_volume FLOAT, 
	yesterday_volume FLOAT, 
	event_type VARCHAR, 
	sentiment_shift TEXT, 
	top_posts TEXT, 
	brief_generated BOOLEAN, 
	root_cause TEXT, 
	report_generated BOOLEAN, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE collection_status (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	source VARCHAR NOT NULL, 
	mode VARCHAR NOT NULL, 
	last_collected_at DATETIME, 
	posts_collected INTEGER, 
	status VARCHAR, 
	error_message TEXT, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, is_running BOOLEAN DEFAULT 0, lock_acquired_at DATETIME, last_refreshed_at DATETIME, skipped_vehicles TEXT, 
	PRIMARY KEY (id)
);

CREATE TABLE defect_themes (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	payload TEXT NOT NULL, 
	computed_at DATETIME DEFAULT CURRENT_TIMESTAMP, window_start TEXT, window_end TEXT, 
	PRIMARY KEY (id)
);

CREATE TABLE dialog_conversations (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	anchor_type VARCHAR, 
	anchor_data TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE dialog_messages (
	id VARCHAR NOT NULL, 
	conversation_id VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	content TEXT NOT NULL, 
	generative_ui TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE event_groups (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	event_tag VARCHAR NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	post_count INTEGER, 
	post_ids TEXT, 
	summary TEXT, 
	sentiment_distribution TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, source VARCHAR DEFAULT 'social', 
	PRIMARY KEY (id)
);

CREATE TABLE heat_metrics (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	date DATE NOT NULL, 
	attention_index FLOAT, 
	discussion_volume INTEGER, 
	media_volume INTEGER, 
	interaction_intensity FLOAT, 
	rank VARCHAR, 
	percentile FLOAT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE post_comments (
	id VARCHAR NOT NULL, 
	post_id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	content TEXT NOT NULL, 
	author VARCHAR, 
	likes INTEGER, 
	platform VARCHAR, 
	published_at DATETIME, 
	collected_at DATETIME DEFAULT CURRENT_TIMESTAMP, dim_sentiment TEXT, cid VARCHAR, comment_polarity TEXT, 
	PRIMARY KEY (id)
);

CREATE TABLE raw_posts (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	source VARCHAR NOT NULL, 
	platform VARCHAR, 
	title VARCHAR, 
	content TEXT NOT NULL, 
	author VARCHAR, 
	url VARCHAR, 
	published_at DATETIME, 
	collected_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	likes INTEGER, 
	comments INTEGER, 
	shares INTEGER, 
	analysis_status VARCHAR, 
	full_content TEXT, 
	duplicate_group_id VARCHAR, 
	relevance_score FLOAT, author_type VARCHAR DEFAULT 'organic', is_promo BOOLEAN DEFAULT 0, 
	PRIMARY KEY (id)
);

CREATE TABLE reports (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	type VARCHAR NOT NULL, 
	anomaly_event_id VARCHAR, 
	title VARCHAR, 
	content TEXT NOT NULL, 
	time_range_start DATE, 
	time_range_end DATE, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );

CREATE TABLE search_index_metrics (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	date DATE NOT NULL, 
	source VARCHAR NOT NULL, 
	keyword VARCHAR NOT NULL, 
	index_value FLOAT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE tikhub_daily_usage (
	date VARCHAR NOT NULL, 
	calls INTEGER NOT NULL, 
	PRIMARY KEY (date)
);

CREATE TABLE vehicle_groups (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	description TEXT, 
	vehicle_ids TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE TABLE vehicles (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	brand VARCHAR NOT NULL, 
	search_keywords TEXT, 
	expanded_keywords TEXT, 
	keywords_expanded_at DATETIME, 
	lifecycle_anchors TEXT, 
	competitor_ids TEXT, 
	status VARCHAR, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, expansion_status VARCHAR DEFAULT 'pending', 
	PRIMARY KEY (id)
);

CREATE TABLE watch_items (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	source_type VARCHAR NOT NULL, 
	source_ref VARCHAR, 
	post_count INTEGER, 
	first_seen DATE NOT NULL, 
	note TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_analyzed_posts_post_id ON analyzed_posts(post_id);
CREATE INDEX idx_analyzed_posts_subject ON analyzed_posts(subject);
CREATE INDEX idx_analyzed_posts_vehicle ON analyzed_posts(vehicle_id);
CREATE UNIQUE INDEX idx_post_comments_cid ON post_comments(post_id, cid) WHERE cid IS NOT NULL;
CREATE INDEX idx_post_comments_post ON post_comments(post_id);
CREATE INDEX idx_post_comments_vehicle ON post_comments(vehicle_id);
CREATE INDEX idx_raw_posts_analysis_status ON raw_posts(analysis_status);
CREATE INDEX idx_raw_posts_author_type ON raw_posts(author_type);
CREATE INDEX idx_raw_posts_published ON raw_posts(published_at);
CREATE INDEX idx_raw_posts_vehicle ON raw_posts(vehicle_id);
