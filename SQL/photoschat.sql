--
-- PostgreSQL database dump
--

\restrict f7H4SRcbnfxiVbCKJkmyxAIY2f8xSnk7kuI7tYCcSYG0kBSAeSVMn27hoqU3lgh

-- Dumped from database version 18.1
-- Dumped by pg_dump version 18.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: photo_faces; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.photo_faces (
    id bigint NOT NULL,
    photo_path text NOT NULL,
    bbox jsonb,
    embedding public.vector(512)
);


ALTER TABLE public.photo_faces OWNER TO postgres;

--
-- Name: photo_faces_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.photo_faces_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.photo_faces_id_seq OWNER TO postgres;

--
-- Name: photo_faces_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.photo_faces_id_seq OWNED BY public.photo_faces.id;


--
-- Name: photo_objects; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.photo_objects (
    pathname character varying(500) NOT NULL,
    object_name character varying(100) NOT NULL,
    confidence double precision NOT NULL
);


ALTER TABLE public.photo_objects OWNER TO postgres;

--
-- Name: photos; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.photos (
    id uuid NOT NULL,
    pathname character varying(500) NOT NULL,
    filename character varying(255) NOT NULL,
    file_extension character varying(10) NOT NULL,
    file_size bigint NOT NULL,
    aperture character varying(50),
    shutter_speed character varying(50),
    iso integer,
    focal_length character varying(50),
    date_taken timestamp without time zone,
    camera_model character varying(255),
    lens_model character varying(255),
    analysis_date timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    gps_lat double precision,
    gps_lon double precision,
    width integer,
    height integer,
    phash bigint,
    embedding public.vector(512),
    caption text,
    analysis_tags tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, (((((((COALESCE(filename, ''::character varying))::text || ' '::text) || (COALESCE(camera_model, ''::character varying))::text) || ' '::text) || (COALESCE(lens_model, ''::character varying))::text) || ' '::text) || COALESCE(caption, ''::text)))) STORED,
    objects text[],
    face_embedding public.vector(512)
);


ALTER TABLE public.photos OWNER TO postgres;

--
-- Name: photo_faces id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.photo_faces ALTER COLUMN id SET DEFAULT nextval('public.photo_faces_id_seq'::regclass);


--
-- Name: photo_faces photo_faces_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.photo_faces
    ADD CONSTRAINT photo_faces_pkey PRIMARY KEY (id);


--
-- Name: photo_objects photo_objects_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.photo_objects
    ADD CONSTRAINT photo_objects_pkey PRIMARY KEY (pathname, object_name);


--
-- Name: photos photos_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.photos
    ADD CONSTRAINT photos_pkey PRIMARY KEY (id);


--
-- Name: photo_faces unique_face; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.photo_faces
    ADD CONSTRAINT unique_face UNIQUE (photo_path, bbox);


--
-- Name: idx_caption_trgm; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_caption_trgm ON public.photos USING gin (caption public.gin_trgm_ops);


--
-- Name: idx_face_embedding; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_face_embedding ON public.photos USING ivfflat (face_embedding) WITH (lists='100');


--
-- Name: idx_object_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_object_name ON public.photo_objects USING btree (object_name);


--
-- Name: idx_phash; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_phash ON public.photos USING btree (phash);


--
-- Name: idx_photos_camera; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_photos_camera ON public.photos USING btree (camera_model);


--
-- Name: idx_photos_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_photos_date ON public.photos USING btree (date_taken);


--
-- Name: idx_photos_embedding; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_photos_embedding ON public.photos USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_photos_filename; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_photos_filename ON public.photos USING btree (filename);


--
-- Name: idx_photos_iso; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_photos_iso ON public.photos USING btree (iso);


--
-- Name: idx_photos_objects; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_photos_objects ON public.photos USING gin (objects);


--
-- Name: idx_photos_tags; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_photos_tags ON public.photos USING gin (analysis_tags);


--
-- Name: photos_embedding_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX photos_embedding_idx ON public.photos USING ivfflat (embedding) WITH (lists='100');


--
-- Name: photos_pathname_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX photos_pathname_idx ON public.photos USING btree (pathname);


--
-- PostgreSQL database dump complete
--

\unrestrict f7H4SRcbnfxiVbCKJkmyxAIY2f8xSnk7kuI7tYCcSYG0kBSAeSVMn27hoqU3lgh

