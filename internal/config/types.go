package config

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"strings"

	"github.com/elliotchance/pie/v2"
	"gopkg.in/yaml.v3"

	"github.com/labd/mach-composer/internal/plugins"
	"github.com/labd/mach-composer/internal/variables"
)

type rawConfig struct {
	MachComposer MachComposer `yaml:"mach_composer"`
	Global       yaml.Node    `yaml:"global"`
	Sites        yaml.Node    `yaml:"sites"`
	Components   yaml.Node    `yaml:"components"`

	document  *yaml.Node                `yaml:"-"`
	filename  string                    `yaml:"-"`
	plugins   *plugins.PluginRepository `yaml:"-"`
	variables *variables.Variables      `yaml:"-"`
}

func (r *rawConfig) validate() error {
	if r.MachComposer.Version == "" {
		return fmt.Errorf("no version")
	}

	if r.filename == "" {
		return fmt.Errorf("filename must be set")
	}
	if r.variables == nil {
		return fmt.Errorf("variables cannot be nil")
	}
	if r.plugins == nil {
		return fmt.Errorf("plugins cannot be nil")
	}

	return nil
}

func (r *rawConfig) computeHash() (string, error) {
	hashConfig := struct {
		MachComposer MachComposer         `json:"mach_composer"`
		Global       yaml.Node            `json:"global"`
		Sites        yaml.Node            `json:"sites"`
		Components   yaml.Node            `json:"components"`
		Filename     string               `json:"filename"`
		Variables    *variables.Variables `json:"variables"`
	}{
		MachComposer: r.MachComposer,
		Global:       r.Global,
		Sites:        r.Sites,
		Components:   r.Components,
		Filename:     r.filename,
		Variables:    r.variables,
	}
	data, err := json.Marshal(hashConfig)
	if err != nil {
		return "", err
	}

	h := sha256.New()
	h.Write(data)
	return hex.EncodeToString(h.Sum(nil)), nil
}

func newRawConfig(filename string, document *yaml.Node) (*rawConfig, error) {
	r := &rawConfig{
		filename:  filename,
		variables: variables.NewVariables(),
		document:  document,
	}
	if err := document.Decode(r); err != nil {
		return nil, fmt.Errorf("failed to unmarshal yaml: %w", err)
	}
	return r, nil
}

type MachConfig struct {
	Filename     string       `yaml:"-"`
	MachComposer MachComposer `yaml:"mach_composer"`
	Global       GlobalConfig `yaml:"global"`
	Sites        []SiteConfig `yaml:"sites"`
	Components   []Component  `yaml:"components"`

	extraFiles  map[string][]byte         `yaml:"-"`
	ConfigHash  string                    `yaml:"-"`
	Plugins     *plugins.PluginRepository `yaml:"-"`
	Variables   *variables.Variables      `yaml:"-"`
	IsEncrypted bool                      `yaml:"-"`
}

func (c *MachConfig) Close() {
	if c.Plugins != nil {
		c.Plugins.Close()
	}
}

func (c *MachConfig) HasSite(ident string) bool {
	for i := range c.Sites {
		if c.Sites[i].Identifier == ident {
			return true
		}
	}
	return false
}

type MachComposer struct {
	Version       any                         `yaml:"version"`
	VariablesFile string                      `yaml:"variables_file"`
	Plugins       map[string]MachPluginConfig `yaml:"plugins"`
}

type MachPluginConfig struct {
	Source  string `yaml:"source"`
	Version string `yaml:"version"`
}

type GlobalConfig struct {
	Environment            string           `yaml:"environment"`
	Cloud                  string           `yaml:"cloud"`
	TerraformStateProvider string           `yaml:"-"`
	TerraformConfig        *TerraformConfig `yaml:"terraform_config"`
}

// Site contains all configuration needed for a site.
type SiteConfig struct {
	Name         string
	Identifier   string
	RawEndpoints map[string]any `yaml:"endpoints"`

	Components []SiteComponent `yaml:"components"`
}

type SiteComponent struct {
	Name      string
	Variables map[string]any
	Secrets   map[string]any

	Definition *Component `yaml:"-"`
}

type Component struct {
	Name         string
	Source       string
	Version      string `yaml:"version"`
	Branch       string
	Integrations []string
	Endpoints    map[string]string `yaml:"endpoints"`
}

type TerraformConfig struct {
	Providers   map[string]string `yaml:"providers"`
	RemoteState map[string]string `yaml:"remote_state"`
}

func (sc SiteComponent) HasCloudIntegration(g *GlobalConfig) bool {
	if sc.Definition == nil {
		log.Fatalf("Component %s was not resolved properly (missing definition)", sc.Name)
	}
	return pie.Contains(sc.Definition.Integrations, g.Cloud)
}

// UseVersionReference indicates if the module should be referenced with the
// version.
// This will be mainly used for development purposes when referring to a local
// directory; versioning is not possible, but we should still be able to define
// a version in our component for the actual function deployment itself.
func (c *Component) UseVersionReference() bool {
	return strings.HasPrefix(c.Source, "git")
}
