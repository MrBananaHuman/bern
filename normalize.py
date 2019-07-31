from datetime import datetime
import os
import time
import socket
import threading

from normalizers.gene_auxiliary_normalizer import load_auxiliary_dict


time_format = '[%d/%b/%Y %H:%M:%S.%f]'


class Normalizer:
    def __init__(self):
        # Normalizer paths
        self.BASE_DIR = 'normalization/resources'
        self.NORM_INPUT_DIR = {
            'disease': os.path.join(self.BASE_DIR, 'inputs/disease'),
            'drug': os.path.join(self.BASE_DIR, 'inputs/chemical'),
            'gene': os.path.join(self.BASE_DIR, 'inputs/gene'),
            'mutation': os.path.join(self.BASE_DIR, 'inputs/mutation'),
            'species': os.path.join(self.BASE_DIR, 'inputs/species'),
        }
        self.NORM_OUTPUT_DIR = {
            'disease': os.path.join(self.BASE_DIR, 'outputs/disease'),
            'drug': os.path.join(self.BASE_DIR, 'outputs/chemical'),
            'gene': os.path.join(self.BASE_DIR, 'outputs/gene'),
            'mutation': os.path.join(self.BASE_DIR, 'outputs/mutation'),
            'species': os.path.join(self.BASE_DIR, 'outputs/species'),
        }
        self.NORM_DICT_PATH = {
            'disease': os.path.join(self.BASE_DIR,
                                    'dictionary/best_dict_Disease.txt'),
            'drug': os.path.join(self.BASE_DIR,
                                 'dictionary/best_dict_ChemicalCompound.txt'),
            'gene': ['setup.txt',
                     os.path.join(self.BASE_DIR,
                                  'dictionary/best_dict_Gene.txt'),
                     os.path.join(self.BASE_DIR,
                                  'dictionary/best_dict_Gene_oldbest.txt'),
                     os.path.join(self.BASE_DIR,
                                  'dictionary/best_dict_Gene_freq.txt')],
            'mutation': os.path.join(self.BASE_DIR,
                                     'dictionary/best_dict_Mutation.txt'),
            'species': os.path.join(self.BASE_DIR,
                                    'dictionary/best_dict_Species.txt'),
        }

        self.METADATA_PATH = {
            'gene': os.path.join(self.BASE_DIR,
                                 'meta/gene_extids_190508.tsv'),
            'disease': os.path.join(self.BASE_DIR,
                                    'meta/disease_meta_190310.tsv'),
            'drug': os.path.join(self.BASE_DIR, 'meta/chem_meta.tsv'),
            'mutation': os.path.join(self.BASE_DIR,
                                     'meta/mutation_synonyms.tsv')
        }

        # Load gid2oid for Gene (only for gene)
        self.gid2oid = dict()
        with open(self.NORM_DICT_PATH['gene'][1], 'r', encoding='utf-8') as f:
            for line in f:
                oid, gids = line.rstrip().split('||')
                for gid in gids.split('|'):
                    bar_idx = gid.find('-')
                    if bar_idx > -1:
                        self.gid2oid[gid[:bar_idx]] = oid
                    else:
                        self.gid2oid[gid] = oid
        print('gid2oid loaded', len(self.gid2oid))

        # Load gene metadata
        self.gid2meta = dict()
        gene_ext_ids = 0
        with open(self.METADATA_PATH['gene'], 'r', encoding='utf-8') as f:
            for line in f:
                cols = line.rstrip().split('\t')
                if len(cols) < 2:
                    print('#cols', len(cols), line.rstrip())
                    continue

                external_ids = cols[1]

                if '' == external_ids.strip():
                    continue

                gene_ext_ids += 1

                external_ids = external_ids.replace('HGNC:HGNC:', 'HGNC:')

                gid = cols[0]
                if gid not in self.gid2oid:
                    print('skip', gid)
                    continue
                self.gid2meta[gid] = external_ids.replace('|', '\t')
        print('gene meta #ids {}, #ext_ids {}'.format(len(self.gid2meta),
                                                      gene_ext_ids))

        # Load disease metadata
        self.did2meta = dict()
        disease_ext_ids = 0
        with open(self.METADATA_PATH['disease'], 'r', encoding='utf-8') as f:
            for line in f:
                cols = line.rstrip().split('\t')
                if len(cols) < 2:
                    print('#cols', len(cols), line.rstrip())
                    continue
                self.did2meta[cols[0]] = cols[1].replace(',', '\t')
                disease_ext_ids += len(cols[1].split(','))
        print('disease meta #ids {}, #ext_ids {}'.format(len(self.did2meta),
                                                         disease_ext_ids))

        # Load chem metadata
        self.cid2meta = dict()
        chem_ext_ids = 0
        with open(self.METADATA_PATH['drug'], 'r', encoding='utf-8') as f:
            for line in f:
                cols = line.rstrip().split('\t')
                if len(cols) < 2:
                    print('#cols', len(cols), line.rstrip())
                    continue
                self.cid2meta[cols[0]] = cols[1].replace(',', '\t')
                chem_ext_ids += len(cols[1].split(','))
        print('chem meta #ids {}, #ext_ids {}'.format(len(self.cid2meta),
                                                      chem_ext_ids))

        self.NORM_MODEL_VERSION = 'dmis ne norm v.20190310'

        self.HOST = '127.0.0.1'

        self.GENE_PORT = 18888
        self.SPECIES_PORT = 18889
        self.CHEMICAL_PORT = 18890
        self.MUT_PORT = 18891
        self.DISEASE_PORT = 18892
        self.NO_ENTITY_ID = 'CUI-less'

    def normalize(self, base_name, doc_dict_list, cur_thread_name, is_raw_text):
        start_time = time.time()

        names = dict()
        saved_items = list()
        ent_cnt = 0
        abs_cnt = 0

        for item in doc_dict_list:

            # Get json values
            abstract = item['abstract']
            # pmid = item['pmid']
            entities = item['entities']

            if not is_raw_text:
                # Title goes with abstract
                if len(abstract) > 0:
                    abstract = ' '.join([item['title'], abstract])
                else:
                    abstract = item['title']

            abs_cnt += 1

            # Iterate entities per abstract
            for ent_type, locs in entities.items():
                ent_cnt += len(locs)
                for loc in locs:

                    loc['end'] += 1

                    if ent_type == 'mutation':
                        name = loc['normalizedName']

                        if ';' in name:
                            name = name.split(';')[0]
                    else:
                        name = abstract[loc['start']:loc['end']]

                    if ent_type in names:
                        names[ent_type].append([name, len(saved_items)])
                    else:
                        names[ent_type] = [[name, len(saved_items)]]

            # Work as pointer
            item['norm_model'] = self.NORM_MODEL_VERSION
            saved_items.append(item)

        # For each entity,
        # 1. Write as input files to normalizers
        # 2. Run normalizers
        # 3. Read output files of normalizers
        # 4. Remove files
        # 5. Return oids

        # Threading
        oids = list()
        threads = list()
        for ent_type in names.keys():
            t = threading.Thread(target=self.run_normalizers_wrap,
                                 args=(ent_type, base_name, names, saved_items,
                                       cur_thread_name, is_raw_text, oids))
            t.daemon = True
            t.start()
            threads.append(t)

        # block until all tasks are done
        for t in threads:
            t.join()

        # Save oids
        cui_less_dict = dict()
        for ent_type, type_oids in oids:
            oid_cnt = 0
            for saved_item in saved_items:
                for loc in saved_item['entities'][ent_type]:
                    # Calculate CUI-less
                    if type_oids[oid_cnt] == self.NO_ENTITY_ID:
                        if ent_type not in cui_less_dict:
                            cui_less_dict[ent_type] = 1
                        else:
                            cui_less_dict[ent_type] += 1

                    # Put oid
                    loc['id'] = type_oids[oid_cnt]
                    oid_cnt += 1
            if ent_type in cui_less_dict:
                print(datetime.now().strftime(time_format),
                      '[{}] Normalizer [{}] {} ratio: {:.3f} ({}/{})'
                      .format(cur_thread_name, ent_type, self.NO_ENTITY_ID,
                              (cui_less_dict.get(ent_type, 0) / len(type_oids)),
                              cui_less_dict.get(ent_type, 0), len(type_oids)))

        print(datetime.now().strftime(time_format),
              '[{}] Normalization models '
              '{:.3f} sec ({} article(s), {} entity type(s))'
              .format(cur_thread_name, time.time() - start_time, abs_cnt,
                      len(names.keys())))

        return saved_items

    def run_normalizers_wrap(self, ent_type, base_name, names, saved_items,
                             cur_thread_name, is_raw_text, results):
        ent_type, oids = self.run_normalizers(ent_type, base_name, names,
                                              saved_items, cur_thread_name,
                                              is_raw_text)
        results.append((ent_type, oids))

    def run_normalizers(self, ent_type, base_name, names, saved_items,
                        cur_thread_name, is_raw_text):
        start_time = time.time()
        name_ptr = names[ent_type]
        oids = list()
        bufsize = 4

        base_thread_name = '{}_{}'.format(base_name, cur_thread_name)
        if ent_type == 'disease':

            # 1. Write as input files to normalizers
            norm_inp_path = os.path.join(self.NORM_INPUT_DIR[ent_type],
                                         base_thread_name + '.concept')
            norm_abs_path = os.path.join(self.NORM_INPUT_DIR[ent_type],
                                         base_thread_name + '.txt')
            with open(norm_inp_path, 'w') as norm_inp_f:
                for name, _ in name_ptr:
                    norm_inp_f.write(name + '\n')
            # created for drug normalizer
            with open(norm_abs_path, 'w') as _:
                pass

            # 2. Run normalizers
            s = socket.socket()
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.connect((self.HOST, self.DISEASE_PORT))
            s.send('Start Sieve'.encode('utf-8'))
            s.recv(bufsize)
            s.close()

            # 3. Read output files of normalizers
            norm_out_path = os.path.join(self.NORM_OUTPUT_DIR[ent_type],
                                         base_thread_name + '.oid')
            with open(norm_out_path, 'r') as norm_out_f:
                for line in norm_out_f:
                    disease_ids = line.rstrip()

                    if '|' in disease_ids:  # multiple
                        bern_disease_ids = list()
                        ext_id_list = list()
                        for did in disease_ids.split('|'):
                            bern_disease_ids.append(did)
                            disease_ext_id = self.did2meta.get(did, '')
                            if disease_ext_id != '':
                                ext_id_list.append(disease_ext_id)

                        bern_dids = '\t'.join(
                            ['BERN:{}'.format(did) for did in bern_disease_ids])
                        if len(ext_id_list) > 0:
                            oids.append(
                                '\t'.join(ext_id_list) + '\t' + bern_dids)
                        else:
                            oids.append(bern_dids)

                    else:  # single
                        disease_ext_id = self.did2meta.get(disease_ids, '')
                        if disease_ext_id != '':
                            oids.append(
                                disease_ext_id + '\tBERN:' + disease_ids)
                        else:
                            if disease_ids != self.NO_ENTITY_ID:
                                oids.append('BERN:' + disease_ids)
                            else:
                                oids.append(self.NO_ENTITY_ID)

            # 4. Remove input files
            os.remove(norm_inp_path)
            os.remove(norm_abs_path)

            # 5. Remove output files
            os.remove(norm_out_path)

        elif ent_type == 'drug':
            # 1. Write as input files to normalizers
            norm_inp_path = os.path.join(self.NORM_INPUT_DIR[ent_type],
                                         base_thread_name + '.concept')
            with open(norm_inp_path, 'w') as norm_inp_f:
                for name, _ in name_ptr:
                    norm_inp_f.write(name + '\n')

            # 2. Run normalizers
            s = socket.socket()
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.connect((self.HOST, self.CHEMICAL_PORT))
            send_args = ' '.join([self.NORM_INPUT_DIR[ent_type],
                                  self.NORM_OUTPUT_DIR[ent_type],
                                  self.NORM_DICT_PATH[ent_type]])
            s.send(send_args.encode('utf-8'))
            s.recv(bufsize)  # wait for normalizer end.
            s.close()

            # 3. Read output files of normalizers
            norm_out_path = os.path.join(self.NORM_OUTPUT_DIR[ent_type],
                                         base_thread_name + '.oid')
            with open(norm_out_path, 'r') as norm_out_f:
                for line in norm_out_f:
                    oid = line.rstrip()
                    meta = self.cid2meta.get(oid, '')
                    if meta != '':
                        oids.append(meta + '\tBERN:' + oid)
                    else:
                        if oid != self.NO_ENTITY_ID:
                            oids.append('BERN:' + oid)
                        else:
                            oids.append(self.NO_ENTITY_ID)

            # 4. Remove input files
            os.remove(norm_inp_path)

            # 5. Remove output files
            os.remove(norm_out_path)

        elif ent_type == 'mutation':
            # 1. Write as input files to normalizers
            norm_inp_path = os.path.join(self.NORM_INPUT_DIR[ent_type],
                                         base_thread_name + '.concept')
            with open(norm_inp_path, 'w') as norm_inp_f:
                for name, _ in name_ptr:
                    norm_inp_f.write(name + '\n')

            # 2. Run normalizers
            s = socket.socket()
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.connect((self.HOST, self.MUT_PORT))
            send_args = ' '.join([self.NORM_INPUT_DIR[ent_type],
                                  self.NORM_OUTPUT_DIR[ent_type],
                                  self.NORM_DICT_PATH[ent_type]])
            s.send(send_args.encode('utf-8'))
            s.recv(bufsize)  # wait for normalizer end.
            s.close()

            # 3. Read output files of normalizers
            norm_out_path = os.path.join(self.NORM_OUTPUT_DIR[ent_type],
                                         base_thread_name + '.oid')
            with open(norm_out_path, 'r') as norm_out_f:
                for line in norm_out_f:
                    oid = line.rstrip()
                    if oid != self.NO_ENTITY_ID:
                        oids.append('BERN:' + oid)
                    else:
                        oids.append(self.NO_ENTITY_ID)

            # 4. Remove input files
            os.remove(norm_inp_path)

            # 5. Remove output files
            os.remove(norm_out_path)

        elif ent_type == 'species':
            # 1. Write as input files to normalizers
            norm_inp_path = os.path.join(self.NORM_INPUT_DIR[ent_type],
                                         base_thread_name + '.concept')
            with open(norm_inp_path, 'w') as norm_inp_f:
                for name, _ in name_ptr:
                    norm_inp_f.write(name + '\n')

            # 2. Run normalizers
            s = socket.socket()
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.connect((self.HOST, self.SPECIES_PORT))
            send_args = ' '.join([self.NORM_INPUT_DIR[ent_type],
                                  self.NORM_OUTPUT_DIR[ent_type],
                                  self.NORM_DICT_PATH[ent_type]])
            s.send(send_args.encode('utf-8'))
            s.recv(bufsize)  # wait for normalizer end.
            s.close()

            # 3. Read output files of normalizers
            norm_out_path = os.path.join(self.NORM_OUTPUT_DIR[ent_type],
                                         base_thread_name + '.oid')
            with open(norm_out_path, 'r') as norm_out_f:
                for line in norm_out_f:
                    oid = line.rstrip()
                    if oid != self.NO_ENTITY_ID:
                        oid = int(oid) // 100
                        # https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=10095
                        # "... please use NCBI:txid10095 ..."
                        oids.append('NCBI:txid{}'.format(oid))
                    else:
                        oids.append(self.NO_ENTITY_ID)

            # 4. Remove input files
            os.remove(norm_inp_path)

            # 5. Remove output files
            os.remove(norm_out_path)

        elif ent_type == 'gene':
            # create socket
            s = socket.socket()
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.connect((self.HOST, self.GENE_PORT))
            _, local_port = s.getsockname()

            # 1. Write as input files to normalizers
            base_thread_port_name = '{}_{}'.format(base_thread_name, local_port)
            norm_inp_path = os.path.join(self.NORM_INPUT_DIR[ent_type],
                                         base_thread_port_name + '.concept')
            norm_abs_path = os.path.join(self.NORM_INPUT_DIR[ent_type],
                                         base_thread_port_name + '.txt')

            space_type = ' ' + ent_type
            with open(norm_inp_path, 'w') as norm_inp_f:
                with open(norm_abs_path, 'w') as norm_abs_f:
                    for saved_item in saved_items:
                        entities = saved_item['entities'][ent_type]
                        if len(entities) == 0:
                            continue

                        if is_raw_text:
                            abstract_title = saved_item['abstract']
                        else:
                            if len(saved_item['abstract']) > 0:
                                abstract_title = \
                                    ' '.join([saved_item['title'],
                                              saved_item['abstract']])
                            else:
                                abstract_title = saved_item['title']

                        ent_names = list()
                        for loc in entities:
                            e_name = abstract_title[loc['start']:loc['end']]
                            if len(e_name) > len(space_type) \
                                    and space_type \
                                    in e_name.lower()[-len(space_type):]:
                                # print('Replace', e_name,
                                #       'w/', e_name[:-len(space_type)])
                                e_name = e_name[:-len(space_type)]

                            ent_names.append(e_name)
                        norm_abs_f.write(saved_item['pmid'] + '||' +
                                         abstract_title + '\n')
                        norm_inp_f.write('||'.join(ent_names) + '\n')

            # 2. Run normalizers
            gene_input_dir = os.path.abspath(
                os.path.join(self.NORM_INPUT_DIR[ent_type]))
            gene_output_dir = os.path.abspath(
                os.path.join(self.NORM_OUTPUT_DIR[ent_type]))
            setup_dir = self.NORM_DICT_PATH[ent_type][0]  # 0 means setup.txt

            # start jar
            jar_args = '\t'.join(
                [gene_input_dir, gene_output_dir, setup_dir]) + '\n'
            s.send(jar_args.encode('utf-8'))
            s.recv(bufsize)
            s.close()

            # 3. Read output files of normalizers
            gene_oldbest_dict = \
                load_auxiliary_dict(self.NORM_DICT_PATH['gene'][2])
            gene_freq_dict = load_auxiliary_dict(self.NORM_DICT_PATH['gene'][3])
            norm_out_path = os.path.join(gene_output_dir,
                                         base_thread_port_name + '.oid')
            if os.path.exists(norm_out_path):
                with open(norm_out_path, 'r') as norm_out_f, \
                        open(norm_inp_path, 'r') as norm_in_f:
                    for l, input_l in zip(norm_out_f, norm_in_f):
                        gene_ids, gene_mentions = l.rstrip().split('||'), \
                                                  input_l.rstrip().split('||')
                        for gene_id, gene_mention in zip(gene_ids,
                                                         gene_mentions):
                            bar_idx = gene_id.find('-')
                            if bar_idx > -1:
                                gene_id = gene_id[:bar_idx]

                            eid = None

                            if gene_id in self.gid2oid:
                                eid = self.gid2oid[gene_id]
                            elif gene_mention in gene_oldbest_dict:
                                eid = gene_oldbest_dict[gene_mention]
                            elif gene_mention in gene_freq_dict:
                                eid = gene_freq_dict[gene_mention]

                            meta = self.gid2meta.get(gene_id, '')
                            if len(meta) > 0:
                                eid = meta + '\tBERN:{}'.format(eid)
                            else:
                                if eid is not None:
                                    eid = 'BERN:{}'.format(eid)
                                else:
                                    eid = self.NO_ENTITY_ID

                            oids.append(eid)

                # 5. Remove output files
                os.remove(norm_out_path)
            else:
                print('Not found!!!', norm_out_path)
                # Sad error handling
                for _ in range(len(name_ptr)):
                    oids.append(self.NO_ENTITY_ID)

            # 4. Remove input files
            os.remove(norm_inp_path)
            os.remove(norm_abs_path)

        # 5. Return oids
        assert len(oids) == len(name_ptr), '{} vs {} in {}'.format(
            len(oids), len(name_ptr), ent_type)

        print(datetime.now().strftime(time_format),
              '[{}] [{}] {:.3f} sec, {} mention(s)'.format(
                  cur_thread_name, ent_type, time.time() - start_time,
                  len(name_ptr)))
        return ent_type, oids
