from mne.time_frequency import psd_array_multitaper
from src.utils.spectral_matrix.spectral_features import SpectralMatrixFeatures
import pandas as pd
import logging
import numpy as np
import pickle as pkl
import os
from pathlib import Path


class FeatureExtractor:
    """
    A class for extracting features from EEG data.

    This class provides methods for extracting various features such as time-domain features,
    coherence features, and frequency-domain features from EEG data.

    Parameters
    ----------
    paths : object
        An object containing various file paths necessary for feature extraction.
    settings : object
        An object containing various settings for feature extraction.

    Attributes
    ----------
    fs : float or None
        The sampling frequency of the EEG data.
    time : numpy array or None
        Time vector for EEG data.
    all_patient_features : dict
        Dictionary to store features for all patients.
    paths : object
        Object containing paths for feature extraction.
    settings : object
        Object containing settings for feature extraction.
    """

    def __init__(self, paths, settings):
        """
        Initialize the FeatureExtractor with EEGDataSet and sampling frequency.

        Args:
        paths (Path): An instance of the EEGDataSet class containing EEG data.
        settings (Settings): analysis settings
        """
        self.fs = None
        self.time = None
        self.all_patient_features = {}
        self.paths = paths
        self.settings = settings
        logging.basicConfig(filename=paths.path_result + 'feature_extraction_log.txt', level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')

    def extract_features(self, eeg_dataset, config):
        """
        Extract features from EEG data for all patients in the EEGDataSet.

        This method iterates over all patient data in the provided EEGDataSet instance
        and extracts features from the EEG data.

        Parameters
        ----------
        eeg_dataset : EEGDataSet
            The EEGDataSet instance containing patient data.

        Returns
        -------
        EEGDataSet
            The EEGDataSet instance with features extracted for each patient.
        """
        features_all_blocks = {}
        for index, (patient_id, patient_dataset) in enumerate(eeg_dataset.all_patient_data.items()):
            # Print progress information
            print(f"Subject {index} from {len(eeg_dataset.all_patient_data.keys())}: {patient_id} Feature Extraction")

            # Log progress information
            logging.info(f"Subject {index} from {len(eeg_dataset.all_patient_data.keys())}: {patient_id} "
                         f"Feature Extraction ...")

            # Set the time and sampling frequency attributes for feature extraction
            self.time = patient_dataset.time_ms
            self.fs = patient_dataset.fs

            # Define the path to save or load feature data
            if self.settings.dataset == 'clear':
                file_name = f"{patient_id.split('.')[0]}_{self.settings.dataset_task}_features.csv"
            else:
                file_name = f"{patient_id}_features.csv"
            feature_file = os.path.join(self.paths.feature_path, file_name)

            # Check if feature data already exists and should be loaded
            if os.path.exists(feature_file) and self.settings.load_features is True:
                # Load and store existing feature data
                self.all_patient_features[patient_id] = self.load_features(feature_file)
                logging.info("Successfully Loaded!")
            else:
                # Extract features for the current patient dataset
                features = self.apply_feature_extraction(patient_dataset, **config)

                # Store the extracted features
                self.all_patient_features[patient_id] = features

                logging.info("Successfully Extracted!")
                features_df = self.feature_dict_to_df(eeg_dataset,
                                                      feature_dict=features,
                                                      patient_id=index,
                                                      patient_file_name=patient_id)

                # Save the features to a file for future use
                if self.settings.save_features is True:
                    features_df.to_csv(feature_file)
                    # self.save_features(features, feature_file)

                features_all_blocks[patient_id] = features_df

        return features_all_blocks

    def feature_dict_to_df(self, eeg_dataset, feature_dict, patient_id, patient_file_name):
        features_list, features_list_name = self.process_patient_features(patient_file_name, feature_dict,
                                                                          eeg_dataset)

        features_matrix = np.concatenate(features_list, axis=1)

        # Create the features matrix DataFrame with initial feature columns
        features_df = pd.DataFrame(features_matrix, columns=features_list_name)

        # Create the patient ID and patient name columns as separate DataFrames
        patients_ids_df = pd.DataFrame({'id': patient_id * np.ones(features_matrix.shape[0])})
        train_patient_name_df = pd.DataFrame({'subject_file': features_matrix.shape[0] * [patient_file_name]})

        # Concatenate all columns (features, patient IDs, and patient names) at once
        features_df = pd.concat([patients_ids_df, train_patient_name_df, features_df], axis=1)

        # Add the labels columns all at once
        labels_df = eeg_dataset.all_patient_data[patient_file_name].labels.copy()
        if features_df.shape[0] < len(labels_df):
            labels_df = labels_df.iloc[:features_df.shape[0]]

        # Concatenate the label DataFrame to the features DataFrame
        features_df = pd.concat([features_df, labels_df], axis=1)

        return features_df

    def apply_feature_extraction(self, dataset, **kwargs) -> dict:
        """
        Apply feature extraction process on the given EEG data.

        Parameters
        ----------
        dataset : EEGDataSet
            An instance of EEGDataSet containing data for feature extraction.

        Returns
        -------
        dict
            A dictionary containing the extracted features.
        """
        # Initialize an empty dictionary to store the extracted features
        features = {}

        for feature_type, params in kwargs.items():
            if feature_type == 'time_n200':
                features['time_n200'] = self.extract_time_features(dataset.data, **params)
            elif feature_type == 'time_p300':
                features['time_p300'] = self.extract_time_features(dataset.data, **params)
            elif feature_type == 'time_post_p300':
                features['time_post_p300'] = self.extract_time_features(dataset.data, **params)
            elif feature_type.startswith('coherence'):
                features.update(self.extract_coherence_features(dataset, **params))
            elif feature_type.startswith('frequency'):
                features.update(self.extract_frequency_features(dataset, **params))
            # Add more feature extraction steps as needed

        return features

    def get_feature_array(self, eeg_dataset):
        """
        Extract features from EEG data for all patients in the EEGDataSet.

        Args:
            eeg_dataset: EEGDataSet instance containing patient data.

        Returns:
            tuple: A tuple containing the extracted features, labels, patient IDs, and feature names.
        """
        initial_labels = eeg_dataset.all_patient_data[list(self.all_patient_features.keys())[0]].labels

        train_data, train_patient, train_patient_name = [], [], []
        train_labels = {key: [] for key in initial_labels.keys()}

        for patient_index, (patient_id, patient_features) in enumerate(self.all_patient_features.items()):
            print(f"Processing patient {patient_index + 1}/{len(self.all_patient_features)}: {patient_id}")
            features_list, features_list_name = self.process_patient_features(patient_id, patient_features, eeg_dataset)

            train_data.append(np.concatenate(features_list, axis=1))
            self.append_labels_and_patient_info(train_labels, eeg_dataset.all_patient_data[patient_id].labels,
                                                patient_index, train_patient, train_patient_name, features_list)

        return self.construct_output(train_data, train_labels, train_patient, train_patient_name)

    def extract_time_features(self, data, start_time=150, end_time=250):
        """
        Extract time-domain features from EEG data within a specified time window.

        Parameters
        ----------
        data : numpy.ndarray
            The EEG data from which to extract time features.
        start_time : int
            The starting time (in ms) for the feature extraction window.
        end_time : int
            The ending time (in ms) for the feature extraction window.

        Returns
        -------
        numpy.ndarray
            Extracted time-domain features.
        """
        # Define time indices based on sampling frequency
        # conversion from time to index based on milli-second
        data = data / np.sqrt(np.sum(np.square(data), axis=-1, keepdims=True))
        ind = self._time_to_indices(start_time=start_time, end_time=end_time)
        return np.mean(data[:, :, ind[0]:ind[1]], axis=-1)

    def extract_coherence_features(self, dataset, time_start=50, end_time=1050):
        """
        Extract coherence features from EEG data.

        Parameters
        ----------
        dataset : EEGDataSet
            The EEGDataSet instance containing the EEG data.
        time_start : int
            The starting time (in ms) for the coherence analysis.
        end_time : int
            The ending time (in ms) for the coherence analysis.

        Returns
        -------
        dict
            A dictionary containing extracted coherence features.
        """
        eeg_data = dataset.data
        channel_groups = dataset.channel_group

        # Convert time to indices
        start_idx, end_idx = self._time_to_indices(time_start, end_time)

        connectivity_features = {}  # Initialize a dictionary to store coherence features

        for ind in range(eeg_data.shape[0]):  # Loop over EEG data samples
            # Assume temp is an MNE Epochs object
            temp = eeg_data[ind]
            max_ch = min(len(ch_list[0]) for ch_list in channel_groups)
            Data = np.zeros((max_ch, len(channel_groups), end_idx - start_idx))

            for grp_idx, ch_list in enumerate(channel_groups):  # Loop over channel groups
                ch_list = np.squeeze(ch_list)
                for ch_idx in range(max_ch):
                    if ch_idx < len(ch_list):
                        ch = ch_list[ch_idx] - 1
                        eeg_x = temp[ch, start_idx:end_idx]  # Extract the EEG segment
                        Data[ch_idx, grp_idx, :] = eeg_x - np.mean(eeg_x)  # Subtract mean and assign
                    else:
                        # Handle cases where the current channel group has less than max_ch channels
                        Data[ch_idx, grp_idx, :] = np.nan  # or some other placeholder value

            # Coherence Analysis
            fmin, fmax = 4, 60  # Define the frequency band of interest

            for method in ['coh']:  # Choose the coherence method (e.g., 'coh', 'imcoh', 'plv', etc.)
                group_names = [f'group{idx}' for idx in range(Data.shape[1])]

                # Initialize an object for spectral matrix features
                spectral_features = SpectralMatrixFeatures(dataset)

                # Calculate the spectral matrix and coherence features
                spectral_features.calculate_matrix(Data, fmin=fmin, fmax=fmax, ch_names=group_names, bandwidth=5,
                                                   adaptive=True, desired_freqs=[4, 8, 13, 30], verbose=False)
                coh_matrix, coh_tot, coh_ent, coh_vec = spectral_features.coherency_matrix()

                # Store the coherence features in the connectivity_features dictionary
                if 'coh_tot_' + method in connectivity_features.keys():
                    connectivity_features['coh_tot_' + method].append(coh_tot)
                else:
                    connectivity_features['coh_tot_' + method] = [coh_tot]

                if 'coh_vec_' + method in connectivity_features.keys():
                    connectivity_features['coh_vec_' + method].append(coh_vec)
                else:
                    connectivity_features['coh_vec_' + method] = [coh_vec]

                connectivity_features['coh_' + method + '_freqs'] = spectral_features.freqs

        # Stack the coherence features into numpy arrays
        for method in connectivity_features.keys():
            connectivity_features[method] = np.stack(connectivity_features[method], axis=0)

        return connectivity_features

    def extract_frequency_features(self, dataset, time_start=0, end_time=750, normalization='z_score'):
        """
        Extract frequency-domain features from EEG data.

        Parameters
        ----------
        dataset : EEGDataSet
            The EEGDataSet instance containing the EEG data.
        time_start : int
            The starting time (in ms) for the frequency analysis.
        end_time : int
            The ending time (in ms) for the frequency analysis.

        Returns
        -------
        dict
            A dictionary containing extracted frequency-domain features.
        """
        eeg_data = dataset.data  # Assuming this is a 3D array (trials x channels x timepoints)
        features = {}

        # Frequency bands
        freq_bands = {
            'delta': (1, 4),
            'theta': (4, 8),
            'alpha': (8, 12),
            'beta': (13, 30),
            'gamma': (30, 45),
            'high-gamma': (60, 115)
        }

        # Convert time to indices
        start_idx, end_idx = self._time_to_indices(time_start, end_time)

        for band_name, freq_range in freq_bands.items():
            # Compute power in the given frequency band
            band_power = self._compute_band_power(eeg_data, freq_range, start_idx, end_idx)

            # Apply normalization
            if normalization == 'total_power':
                total_power = np.sum(band_power, axis=-1, keepdims=True)
                normalized_power = band_power / total_power
            elif normalization == 'z_score':
                mean_power = np.mean(band_power, axis=-1, keepdims=True)
                std_power = np.std(band_power, axis=-1, keepdims=True)
                normalized_power = (band_power - mean_power) / std_power
            else:
                normalized_power = band_power

            features[f'freq_{band_name}_time_{time_start}_to_{end_time}'] = normalized_power

        return features

    def _compute_band_power(self, eeg_data, freq_range, start_idx, end_idx):
        """
        Compute the average power in a specific frequency band for EEG data.

        Parameters
        ----------
        eeg_data : numpy.ndarray
            The EEG data for power computation.
        freq_range : tuple
            A tuple containing the lower and upper frequency limits of the band.
        start_idx : int
            The starting index for the analysis.
        end_idx : int
            The ending index for the analysis.

        Returns
        -------
        numpy.ndarray
            The average power in the specified frequency band.
        """
        band_power = []
        for trial in eeg_data:
            # Compute PSD using multitaper method
            psd, freqs = psd_array_multitaper(trial[:, start_idx:end_idx], sfreq=self.fs,
                                              fmin=freq_range[0], fmax=freq_range[1],
                                              adaptive=True, normalization='full', verbose=False)
            # Average power in the frequency band
            avg_power = np.mean(psd, axis=-1)  # Average across frequencies

            band_power.append(avg_power)
        return np.array(band_power)

    def _time_to_indices(self, start_time, end_time):
        """
        Convert time in milliseconds to indices in the EEG data array.

        Parameters
        ----------
        start_time : int
            The start time in milliseconds.
        end_time : int
            The end time in milliseconds.

        Returns
        -------
        tuple
            A tuple containing the start and end indices corresponding to the given times.
        """
        start_index = np.argmin(np.abs(self.time - start_time))
        end_index = np.argmin(np.abs(self.time - end_time))
        return start_index, end_index

    def save_features(self, features, file_path):
        """
        Save extracted features to a file.

        Parameters
        ----------
        features : dict
            The extracted features to be saved.
        file_path : str
            The file path where the features will be saved.
        """

        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'wb') as f:
            pkl.dump(features, f)

    def load_features(self, file_path):
        """
        Load features from a file.

        Parameters
        ----------
        file_path : str
            The file path from which to load the features.

        Returns
        -------
        dict
            The loaded features.
        """
        with open(file_path, 'rb') as f:
            return pkl.load(f)

    def process_patient_features(self, patient_id, patient_features, eeg_dataset):
        """
        Process and extract features for a specific patient.

        Args:
            patient_id: The ID of the patient.
            patient_features: A dictionary of features for the patient.
            eeg_dataset: EEGDataSet instance containing patient data.

        Returns:
            tuple: A tuple containing a list of feature arrays and a list of feature names.
        """
        features_list, features_list_name = [], []
        channel_names = eeg_dataset.all_patient_data[patient_id].channel_names

        self.process_dataset_specific_features(patient_id, eeg_dataset)

        for feature_name, subject_features in patient_features.items():
            if not (feature_name.startswith('coh_') and feature_name.endswith('_freqs')):
                feature_labels = self.get_feature_labels(feature_name, subject_features, channel_names)
                if subject_features.shape[-1] != len(feature_labels):
                    raise ValueError("Feature labels should be the same size as subject features.")

                features_list_name.extend(feature_labels)
                features_list.append(subject_features)

        return features_list, features_list_name

    def process_dataset_specific_features(self, patient_id, eeg_dataset):
        """
        Process dataset-specific features for a patient.

        Args:
            patient_id: The ID of the patient.
            eeg_dataset: EEGDataSet instance containing patient data.
        """
        if self.settings.dataset == 'pilot01':
            response_time_patient = eeg_dataset.all_patient_data[patient_id].response_time[:, None]
        elif self.settings.dataset == 'verbmem':
            old_new_label = eeg_dataset.all_patient_data[patient_id].trial_type - 1
            decision_label = eeg_dataset.all_patient_data[patient_id].decision * 0.5 + 0.5
            trial_block = eeg_dataset.all_patient_data[patient_id].block_number

    def get_feature_labels(self, feature_name, subject_features, channel_names):
        """
        Generate feature labels based on the feature name and subject features.

        Args:
            feature_name: The name of the feature.
            subject_features: The feature data for the subject.
            channel_names: List of channel names from the EEG data.

        Returns:
            list: A list of feature labels.
        """
        if subject_features.shape[-1] == len(channel_names):
            return [f"{ch}-{feature_name}" for ch in channel_names]
        elif feature_name == 'coh_tot_coh':
            return [f"total coherency {freq}" for freq in ['5', '8', '13', '30']]
        else:
            subject_features = subject_features.reshape(subject_features.shape[0], -1)
            frequencies = [5, 8, 13, 30]
            groups = [f"group{idx}" for idx in range(8)]
            return [f"coh_vec_coh_{freq}_{group}" for freq in frequencies for group in groups]

    def append_labels_and_patient_info(self, train_labels, labels, patient_index, train_patient, train_patient_name,
                                       features_list):
        """
        Append the labels and patient information for the current patient.

        Args:
            train_labels: Dictionary to store training labels for all patients.
            labels: Labels for the current patient.
            patient_index: Index of the current patient.
            train_patient: List to store patient indices.
            train_patient_name: List to store patient names.
            features_list: List of extracted features for the current patient.
        """
        for key in train_labels.keys():
            train_labels[key].append(labels[key])

        train_patient.append(np.ones(features_list[-1].shape[0]) * patient_index)
        train_patient_name.extend([patient_index] * features_list[-1].shape[0])

    def construct_output(self, train_data, train_labels, train_patient, train_patient_name):
        """
        Construct the final output consisting of features, labels, patient IDs, and feature names.

        Args:
            train_data: List of feature arrays for all patients.
            train_labels: Dictionary of labels for all patients.
            train_patient: List of patient indices.
            train_patient_name: List of patient names.

        Returns:
            tuple: A tuple containing the extracted features, labels, patient IDs, and feature names.
        """
        patients_ids = np.concatenate(train_patient, axis=0)
        labels_array = {key: np.concatenate(value, axis=0) for key, value in train_labels.items()}
        features_matrix = np.concatenate(train_data, axis=0)

        features_df = pd.DataFrame(features_matrix, columns=train_labels.keys())
        features_df['id'] = patients_ids
        features_df['subject_file'] = train_patient_name

        for key in train_labels.keys():
            if features_df.shape[0] < len(labels_array[key]):
                features_df[key] = labels_array[key][:features_df.shape[0]]
            else:
                features_df[key] = labels_array[key]

        return features_df, features_matrix, labels_array, patients_ids, list(train_labels.keys())
